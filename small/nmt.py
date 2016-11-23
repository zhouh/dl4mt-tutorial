'''
Build a neural machine translation model with soft attention
'''
import theano
import theano.tensor as tensor
from theano.sandbox.rng_mrg import MRG_RandomStreams as RandomStreams

import cPickle as pkl
import ipdb
import numpy
import copy

import os
import warnings
import sys
import time

from collections import OrderedDict

from training_data_iterator import TrainingTextIterator
from data_iterator import TextIterator


profile = False


# push parameters to Theano shared variables
def zipp(params, tparams):
    for kk, vv in params.iteritems():
        tparams[kk].set_value(vv)


# pull parameters from Theano shared variables
def unzip(zipped):
    new_params = OrderedDict()
    for kk, vv in zipped.iteritems():
        new_params[kk] = vv.get_value()
    return new_params


# get the list of parameters: Note that tparams must be OrderedDict
def itemlist(tparams):
    return [vv for kk, vv in tparams.iteritems()]


# dropout
def dropout_layer(state_before, use_noise, trng):
    proj = tensor.switch(
        use_noise,
        state_before * trng.binomial(state_before.shape, p=0.5, n=1,
                                     dtype=state_before.dtype),
        state_before * 0.5)
    return proj


# make prefix-appended name
def _p(pp, name):
    return '%s_%s' % (pp, name)


# initialize Theano shared variables according to the initial parameters
def init_tparams(params):
    tparams = OrderedDict()
    for kk, pp in params.iteritems():
        tparams[kk] = theano.shared(params[kk], name=kk)
    return tparams


# load parameters
def load_params(path, params):
    pp = numpy.load(path)
    for kk, vv in params.iteritems():
        if kk not in pp:
            warnings.warn('%s is not in the archive' % kk)
            continue
        params[kk] = pp[kk]

    return params

# layers: 'name': ('parameter initializer', 'feedforward')
layers = {'ff': ('param_init_fflayer', 'fflayer'),
          'gru': ('param_init_gru', 'gru_layer'),
          'gru_cond': ('param_init_gru_cond', 'gru_cond_layer'),
          }


def get_layer(name):
    fns = layers[name]
    return (eval(fns[0]), eval(fns[1]))


# some utilities
def ortho_weight(ndim):
    W = numpy.random.randn(ndim, ndim)
    u, s, v = numpy.linalg.svd(W)
    return u.astype('float32')


def norm_weight(nin, nout=None, scale=0.01, ortho=True):
    if nout is None:
        nout = nin
    if nout == nin and ortho:
        W = ortho_weight(nin)
    else:
        W = scale * numpy.random.randn(nin, nout)
    return W.astype('float32')


def tanh(x):
    return tensor.tanh(x)


def linear(x):
    return x


def concatenate(tensor_list, axis=0):
    """
    Alternative implementation of `theano.tensor.concatenate`.
    This function does exactly the same thing, but contrary to Theano's own
    implementation, the gradient is implemented on the GPU.
    Backpropagating through `theano.tensor.concatenate` yields slowdowns
    because the inverse operation (splitting) needs to be done on the CPU.
    This implementation does not have that problem.
    :usage:
        >>> x, y = theano.tensor.matrices('x', 'y')
        >>> c = concatenate([x, y], axis=1)
    :parameters:
        - tensor_list : list
            list of Theano tensor expressions that should be concatenated.
        - axis : int
            the tensors will be joined along this axis.
    :returns:
        - out : tensor
            the concatenated tensor expression.
    """
    concat_size = sum(tt.shape[axis] for tt in tensor_list)

    output_shape = ()
    for k in range(axis):
        output_shape += (tensor_list[0].shape[k],)
    output_shape += (concat_size,)
    for k in range(axis + 1, tensor_list[0].ndim):
        output_shape += (tensor_list[0].shape[k],)

    out = tensor.zeros(output_shape)
    offset = 0
    for tt in tensor_list:
        indices = ()
        for k in range(axis):
            indices += (slice(None),)
        indices += (slice(offset, offset + tt.shape[axis]),)
        for k in range(axis + 1, tensor_list[0].ndim):
            indices += (slice(None),)

        out = tensor.set_subtensor(out[indices], tt)
        offset += tt.shape[axis]

    return out



# batch preparation
def prepare_training_data(seqs_x, seqs_y_c, seqs_y_cw, maxlen_chunk=None, maxlen_cw=None, n_words_src=30000,
                 n_words=30000):
    # x: a list of sentences
    lengths_x = [len(s) for s in seqs_x]
    lengths_y_c = [len(s) for s in seqs_y_c]
    lengths_y_cw = [ [len(s) for s in ss] for ss in seqs_y_cw]


    #
    # becasuse we have filtered the out of max size sentence in the iterator, so we do not need it here!
    #
    # if maxlen_chunk is not None or maxlen_cw is not None:
    #     new_seqs_x = []
    #     new_seqs_y_c = []
    #     new_seqs_y_cw = []
    #     new_lengths_x = []
    #     new_lengths_y_c = []
    #     new_lengths_y_cw = []
    #     for l_x, s_x, l_y, s_y in zip(lengths_x, seqs_x, lengths_y_c, seqs_y):
    #         if l_x < maxlen and l_y < maxlen:
    #             new_seqs_x.append(s_x)
    #             new_lengths_x.append(l_x)
    #             new_seqs_y.append(s_y)
    #             new_lengths_y.append(l_y)
    #     lengths_x = new_lengths_x
    #     seqs_x = new_seqs_x
    #     lengths_y = new_lengths_y
    #     seqs_y = new_seqs_y
    #
    #     if len(lengths_x) < 1 or len(lengths_y) < 1:
    #         return None, None, None, None

    n_samples = len(seqs_x)
    maxlen_x = numpy.max(lengths_x) + 1
    maxlen_y_c = numpy.max(lengths_y_c) + 1
    maxlen_y_cw = numpy.max([ numpy.max(a) for a in lengths_y_cw]) + 1

    x = numpy.zeros((maxlen_x, n_samples)).astype('int64')
    y_c = numpy.zeros((maxlen_y_c, n_samples)).astype('int64')
    y_cw = numpy.zeros((maxlen_y_c, maxlen_y_cw, n_samples)).astype('int64')
    x_mask = numpy.zeros((maxlen_x, n_samples)).astype('float32')
    y_mask_c = numpy.zeros((maxlen_y_c, n_samples)).astype('float32')
    y_mask_cw = numpy.zeros((maxlen_y_c, maxlen_y_cw, n_samples)).astype('float32')

    for idx, [s_x, s_y_c, s_y_cw] in enumerate(zip(seqs_x, seqs_y_c, seqs_y_cw)):
        x[:lengths_x[idx], idx] = s_x
        x_mask[:lengths_x[idx]+1, idx] = 1.
        y_c[:lengths_y_c[idx], idx] = s_y_c
        y_mask_c[:lengths_y_c[idx]+1, idx] = 1.

        # y_cw[ lengths_y_c[idx], lengths_y_cw[idx][idx_cw], idx] = s_y_cw

        for idx_cw, s_y_cw_i in enumerate(s_y_cw):
            y_cw[ idx_cw, :lengths_y_cw[idx][idx_cw], idx] = s_y_cw_i
            y_mask_cw[ idx_cw, :lengths_y_cw[idx][idx_cw] + 1, idx] = 1

    # print y_cw

    return x, x_mask, y_c, y_mask_c, y_cw, y_mask_cw

# batch preparation
def prepare_data(seqs_x, seqs_y, maxlen=None, n_words_src=30000,
                 n_words=30000):
    # x: a list of sentences
    lengths_x = [len(s) for s in seqs_x]
    lengths_y = [len(s) for s in seqs_y]

    if maxlen is not None:
        new_seqs_x = []
        new_seqs_y = []
        new_lengths_x = []
        new_lengths_y = []
        for l_x, s_x, l_y, s_y in zip(lengths_x, seqs_x, lengths_y, seqs_y):
            if l_x < maxlen and l_y < maxlen:
                new_seqs_x.append(s_x)
                new_lengths_x.append(l_x)
                new_seqs_y.append(s_y)
                new_lengths_y.append(l_y)
        lengths_x = new_lengths_x
        seqs_x = new_seqs_x
        lengths_y = new_lengths_y
        seqs_y = new_seqs_y

        if len(lengths_x) < 1 or len(lengths_y) < 1:
            return None, None, None, None

    n_samples = len(seqs_x)
    maxlen_x = numpy.max(lengths_x) + 1
    maxlen_y = numpy.max(lengths_y) + 1

    x = numpy.zeros((maxlen_x, n_samples)).astype('int64')
    y = numpy.zeros((maxlen_y, n_samples)).astype('int64')
    x_mask = numpy.zeros((maxlen_x, n_samples)).astype('float32')
    y_mask = numpy.zeros((maxlen_y, n_samples)).astype('float32')
    for idx, [s_x, s_y] in enumerate(zip(seqs_x, seqs_y)):
        x[:lengths_x[idx], idx] = s_x
        x_mask[:lengths_x[idx]+1, idx] = 1.
        y[:lengths_y[idx], idx] = s_y
        y_mask[:lengths_y[idx]+1, idx] = 1.

    return x, x_mask, y, y_mask


# feedforward layer: affine transformation + point-wise nonlinearity
def param_init_fflayer(options, params, prefix='ff', nin=None, nout=None,
                       ortho=True):
    if nin is None:
        nin = options['dim_proj']
    if nout is None:
        nout = options['dim_proj']
    params[_p(prefix, 'W')] = norm_weight(nin, nout, scale=0.01, ortho=ortho)
    params[_p(prefix, 'b')] = numpy.zeros((nout,)).astype('float32')

    return params


def fflayer(tparams, state_below, options, prefix='rconv',
            activ='lambda x: tensor.tanh(x)', **kwargs):
    return eval(activ)(
        tensor.dot(state_below, tparams[_p(prefix, 'W')]) +
        tparams[_p(prefix, 'b')])


# GRU layer
def param_init_gru(options, params, prefix='gru', nin=None, dim=None):
    if nin is None:
        nin = options['dim_proj']
    if dim is None:
        dim = options['dim_proj']

    # embedding to gates transformation weights, biases
    W = numpy.concatenate([norm_weight(nin, dim),
                           norm_weight(nin, dim)], axis=1)
    params[_p(prefix, 'W')] = W
    params[_p(prefix, 'b')] = numpy.zeros((2 * dim,)).astype('float32')

    # recurrent transformation weights for gates
    U = numpy.concatenate([ortho_weight(dim),
                           ortho_weight(dim)], axis=1)
    params[_p(prefix, 'U')] = U

    # embedding to hidden state proposal weights, biases
    Wx = norm_weight(nin, dim)
    params[_p(prefix, 'Wx')] = Wx
    params[_p(prefix, 'bx')] = numpy.zeros((dim,)).astype('float32')

    # recurrent transformation weights for hidden state proposal
    Ux = ortho_weight(dim)
    params[_p(prefix, 'Ux')] = Ux

    return params


def gru_layer(tparams, state_below, options, prefix='gru', mask=None,
              **kwargs):
    nsteps = state_below.shape[0]
    if state_below.ndim == 3:
        n_samples = state_below.shape[1]
    else:
        n_samples = 1

    dim = tparams[_p(prefix, 'Ux')].shape[1]

    if mask is None:
        mask = tensor.alloc(1., state_below.shape[0], 1)

    # utility function to slice a tensor
    def _slice(_x, n, dim):
        if _x.ndim == 3:
            return _x[:, :, n*dim:(n+1)*dim]
        return _x[:, n*dim:(n+1)*dim]

    # state_below is the input word embeddings
    # input to the gates, concatenated
    state_below_ = tensor.dot(state_below, tparams[_p(prefix, 'W')]) + \
        tparams[_p(prefix, 'b')]
    # input to compute the hidden state proposal
    state_belowx = tensor.dot(state_below, tparams[_p(prefix, 'Wx')]) + \
        tparams[_p(prefix, 'bx')]

    # step function to be used by scan
    # arguments    | sequences |outputs-info| non-seqs
    def _step_slice(m_, x_, xx_, h_, U, Ux):
        preact = tensor.dot(h_, U)
        preact += x_

        # reset and update gates
        r = tensor.nnet.sigmoid(_slice(preact, 0, dim))
        u = tensor.nnet.sigmoid(_slice(preact, 1, dim))

        # compute the hidden state proposal
        preactx = tensor.dot(h_, Ux)
        preactx = preactx * r
        preactx = preactx + xx_

        # hidden state proposal
        h = tensor.tanh(preactx)

        # leaky integrate and obtain next hidden state
        h = u * h_ + (1. - u) * h
        h = m_[:, None] * h + (1. - m_)[:, None] * h_

        return h

    # prepare scan arguments
    seqs = [mask, state_below_, state_belowx]
    init_states = [tensor.alloc(0., n_samples, dim)]
    _step = _step_slice
    shared_vars = [tparams[_p(prefix, 'U')],
                   tparams[_p(prefix, 'Ux')]]

    rval, updates = theano.scan(_step,
                                sequences=seqs,
                                outputs_info=init_states,
                                non_sequences=shared_vars,
                                name=_p(prefix, '_layers'),
                                n_steps=nsteps,
                                profile=profile,
                                strict=True)
    rval = [rval]
    return rval


# Conditional GRU layer with Attention
def param_init_gru_cond(options, params, prefix='gru_cond',
                        nin=None, dim=None, dimctx=None,
                        nin_nonlin=None, dim_nonlin=None, nin_chunk=None, nin_nonlin_chunk=None):
    if nin is None:
        nin = options['dim']
    if dim is None:
        dim = options['dim']
    if dimctx is None:
        dimctx = options['dim']
    if nin_nonlin is None:
        nin_nonlin = nin
    if dim_nonlin is None:
        dim_nonlin = dim
    if nin_chunk is None:
        nin_chunk = nin
    if nin_nonlin_chunk is None:
        nin_nonlin_chunk = nin_chunk

    W = numpy.concatenate([norm_weight(nin, dim),
                           norm_weight(nin, dim)], axis=1)
    params[_p(prefix, 'W')] = W
    params[_p(prefix, 'b')] = numpy.zeros((2 * dim,)).astype('float32')
    U = numpy.concatenate([ortho_weight(dim_nonlin),
                           ortho_weight(dim_nonlin)], axis=1)
    params[_p(prefix, 'U')] = U

    Wx = norm_weight(nin_nonlin, dim_nonlin)
    params[_p(prefix, 'Wx')] = Wx
    Ux = ortho_weight(dim_nonlin)
    params[_p(prefix, 'Ux')] = Ux
    params[_p(prefix, 'bx')] = numpy.zeros((dim_nonlin,)).astype('float32')

    U_nl = numpy.concatenate([ortho_weight(dim_nonlin),
                              ortho_weight(dim_nonlin)], axis=1)
    params[_p(prefix, 'U_nl')] = U_nl
    params[_p(prefix, 'b_nl')] = numpy.zeros((2 * dim_nonlin,)).astype('float32')

    Ux_nl = ortho_weight(dim_nonlin)
    params[_p(prefix, 'Ux_nl')] = Ux_nl
    params[_p(prefix, 'bx_nl')] = numpy.zeros((dim_nonlin,)).astype('float32')

    # context to LSTM
    Wc = norm_weight(dimctx, dim*2)
    params[_p(prefix, 'Wc')] = Wc

    Wcx = norm_weight(dimctx, dim)
    params[_p(prefix, 'Wcx')] = Wcx

    # attention: combined -> hidden
    W_comb_att = norm_weight(dim, dimctx)
    params[_p(prefix, 'W_comb_att')] = W_comb_att

    # attention: context -> hidden
    Wc_att = norm_weight(dimctx)
    params[_p(prefix, 'Wc_att')] = Wc_att

    # attention: hidden bias
    b_att = numpy.zeros((dimctx,)).astype('float32')
    params[_p(prefix, 'b_att')] = b_att

    # attention:
    U_att = norm_weight(dimctx, 1)
    params[_p(prefix, 'U_att')] = U_att
    c_att = numpy.zeros((1,)).astype('float32')
    params[_p(prefix, 'c_tt')] = c_att


    # new the chunking parameters


    W_chunk = numpy.concatenate([norm_weight(nin_chunk, dim),
                           norm_weight(nin_chunk, dim)], axis=1) # nin * 2 dim
    params[_p(prefix, 'W_chunk')] = W_chunk
    params[_p(prefix, 'b_chunk')] = numpy.zeros((2 * dim,)).astype('float32')

    U_chunk = numpy.concatenate([ortho_weight(dim_nonlin),
                           ortho_weight(dim_nonlin)], axis=1)
    params[_p(prefix, 'U_chunk')] = U_chunk

    Wx_chunk = norm_weight(nin_nonlin_chunk, dim_nonlin)
    params[_p(prefix, 'Wx_chunk')] = Wx_chunk
    Ux_chunk = ortho_weight(dim_nonlin)
    params[_p(prefix, 'Ux_chunk')] = Ux_chunk
    params[_p(prefix, 'bx_chunk')] = numpy.zeros((dim_nonlin,)).astype('float32')

    U_nl_chunk = numpy.concatenate([ortho_weight(dim_nonlin),
                              ortho_weight(dim_nonlin)], axis=1)
    params[_p(prefix, 'U_nl_chunk')] = U_nl_chunk
    params[_p(prefix, 'b_nl_chunk')] = numpy.zeros((2 * dim_nonlin,)).astype('float32')

    Ux_nl_chunk = ortho_weight(dim_nonlin)
    params[_p(prefix, 'Ux_nl_chunk')] = Ux_nl_chunk
    params[_p(prefix, 'bx_nl_chunk')] = numpy.zeros((dim_nonlin,)).astype('float32')

    # context to LSTM
    Wc_chunk = norm_weight(dimctx, dim*2)
    params[_p(prefix, 'Wc_chunk')] = Wc_chunk

    Wcx_chunk = norm_weight(dimctx, dim)
    params[_p(prefix, 'Wcx_chunk')] = Wcx_chunk

    # attention: combined -> hidden
    W_comb_att_chunk = norm_weight(dim, dimctx)
    params[_p(prefix, 'W_comb_att_chunk')] = W_comb_att_chunk

    # attention: context -> hidden
    Wc_att_chunk = norm_weight(dimctx)
    params[_p(prefix, 'Wc_att_chunk')] = Wc_att_chunk

    # attention: hidden bias
    b_att_chunk = numpy.zeros((dimctx,)).astype('float32')
    params[_p(prefix, 'b_att_chunk')] = b_att_chunk

    # attention:
    U_att_chunk = norm_weight(dimctx, 1)
    params[_p(prefix, 'U_att_chunk')] = U_att_chunk
    c_att_chunk = numpy.zeros((1,)).astype('float32')
    params[_p(prefix, 'c_tt_chunk')] = c_att_chunk



    return params


def gru_cond_layer(tparams, emb, chunk_emb, options, prefix='gru',
                   chunk_mask=None,chunk_word_mask=None,
                   context=None, one_step_chunk=False,
                   one_step_word=False,
                   init_memory=None, init_state=None,
                   init_state_chunk=None,init_state_chunk_words=None,
                   context_mask=None,n_chunk_step=1,n_chunk_word_step=1,
                   **kwargs):

    #
    # #
    # # x = tensor.matrix('temp_x', dtype='int64')
    # x_printed = theano.printing.Print('this is a very important value')(chunk_word_mask)
    # f_with_print = theano.function([chunk_word_mask], x_printed)
    # assert numpy.all( f_with_print([[1,2],[1,2]]))

    assert context, 'Context must be provided'

    if one_step_word:
        assert init_state_chunk_words, 'previous state must be provided'

    if one_step_chunk:
        assert init_state_chunk, 'previous state must be provided'

    if  one_step_chunk == False and one_step_word == False:
        assert init_state_chunk_words, 'previous state must be provided'
        assert init_state_chunk, 'previous state must be provided'

    #
    # n_chunk_step = chunk_emb.shape[0]
    # n_chunk_words_step = emb.shape[1]


    # if this is a sample or decode process, we may use a sample = 1 predict
    if chunk_emb is not None:
        if chunk_emb.ndim == 3:
            n_samples = chunk_emb.shape[1]
        else:
            n_samples = 1
    else:
        if emb.ndim == 4:
            n_samples = emb.shape[1]
        else:
            n_samples = 1


    # mask
    # we have no mask during sample and translate, we have one sample for gen sample,
    # and for beam search, the sample size are not fixed, we leave out the ended traslate.
    #
    # if the mask is None, one_step_chunk and one_step_word are always not both False, that means it's
    # not the training process.
    if chunk_mask is None and chunk_emb is not None:
        chunk_mask = tensor.alloc(1., chunk_emb.shape[0], 1)
    if chunk_word_mask is None and emb is not None:
        chunk_word_mask = tensor.alloc(1., emb.shape[0], 1)

    # the hidden dim
    dim = tparams[_p(prefix, 'Wcx')].shape[1]


    # initial/previous state
    if init_state_chunk is None:
        init_state_chunk = tensor.alloc(0., n_samples, dim)
    if init_state_chunk_words is None:
        init_state_chunk_words = tensor.alloc(0., n_samples, dim)

    # projected context
    assert context.ndim == 3, \
        'Context must be 3-d: #annotation x #sample x dim'


    def _slice(_x, n, dim):
        if _x.ndim == 3:
            return _x[:, :, n*dim:(n+1)*dim]
        return _x[:, n*dim:(n+1)*dim]


    # # TODO just for test, for the variable
    # pctx_ = tensor.dot(context, tparams[_p(prefix, 'Wc_att')]) + \
    #     tparams[_p(prefix, 'b_att')]
    #
    # # chunk pctx
    # chunk_pctx_ = tensor.dot(context, tparams[_p(prefix, 'Wc_att_chunk')]) + \
    #           tparams[_p(prefix, 'b_att_chunk')]
    #
    #
    #
    # # projected x
    # state_belowx = tensor.dot(emb, tparams[_p(prefix, 'Wx')]) +\
    #     tparams[_p(prefix, 'bx')]
    # state_below_ = tensor.dot(emb, tparams[_p(prefix, 'W')]) +\
    #     tparams[_p(prefix, 'b')]
    #
    #
    # # projected x
    # chunk_state_belowx = tensor.dot(chunk_emb, tparams[_p(prefix, 'Wx_chunk')]) +\
    #     tparams[_p(prefix, 'bx_chunk')]
    # chunk_state_below_ = tensor.dot(chunk_emb, tparams[_p(prefix, 'W_chunk')]) +\
    #     tparams[_p(prefix, 'b_chunk')]

    #
    #
    # if one_step_word == False and one_step_chunk == False: # be in training
    #
    # elif one_step_word == True:
    #
    # elif one_step_chunk == True:
    #



    # word slice in a chunk
    # I even do not modify the function.
    def _step_slice(m_, x_, xx_,
                    h_, ctx_, alpha_,
                    pctx_, cc_,
                    U, Wc, W_comb_att, U_att, c_tt, Ux, Wcx, U_nl, Ux_nl, b_nl, bx_nl):
        preact1 = tensor.dot(h_, U)
        preact1 += x_
        preact1 = tensor.nnet.sigmoid(preact1)
        preact1 = tensor.dot(h_, U)
        preact1 += x_
        preact1 = tensor.nnet.sigmoid(preact1)

        r1 = _slice(preact1, 0, dim)
        u1 = _slice(preact1, 1, dim)

        preactx1 = tensor.dot(h_, Ux)
        preactx1 *= r1
        preactx1 += xx_

        h1 = tensor.tanh(preactx1)

        h1 = u1 * h_ + (1. - u1) * h1


        h1 = m_[:, None] * h1 + (1. - m_)[:, None] * h_


        #
        # # x = tensor.matrix('temp_x', dtype='int64')
        # x_printed = theano.printing.Print('this is a very important value')(context_mask)
        # f_with_print = theano.function([context_mask], x_printed)
        # assert numpy.all( f_with_print([[1,1],[1,1]]))


        # attention
        pstate_ = tensor.dot(h1, W_comb_att)
        pctx__ = pctx_ + pstate_[None, :, :]
        #pctx__ += xc_
        pctx__ = tensor.tanh(pctx__)
        alpha = tensor.dot(pctx__, U_att)+c_tt
        alpha = alpha.reshape([alpha.shape[0], alpha.shape[1]])
        alpha = tensor.exp(alpha)
        if context_mask:
            alpha = alpha * context_mask
        alpha = alpha / alpha.sum(0, keepdims=True)
        ctx_ = (cc_ * alpha[:, :, None]).sum(0)  # current context

        #
        # # x = tensor.matrix('temp_x', dtype='int64')
        # x_printed = theano.printing.Print('this is a very important value')(context_mask)
        # f_with_print = theano.function([context_mask], x_printed)
        # assert numpy.all( f_with_print([[2,2],[2,2]]))


        preact2 = tensor.dot(h1, U_nl)+b_nl

        #
        # # x = tensor.matrix('temp_x', dtype='int64')
        # x_printed = theano.printing.Print('this is a very important value')(context_mask)
        # f_with_print = theano.function([context_mask], x_printed)
        # assert numpy.all( f_with_print([[3,3],[3,3]]))


        preact2 += tensor.dot(ctx_, Wc)
        preact2 = tensor.nnet.sigmoid(preact2)

        #
        # # x = tensor.matrix('temp_x', dtype='int64')
        # x_printed = theano.printing.Print('this is a very important value')(context_mask)
        # f_with_print = theano.function([context_mask], x_printed)
        # assert numpy.all( f_with_print([[4,4],[4,4]]))

        r2 = _slice(preact2, 0, dim)
        u2 = _slice(preact2, 1, dim)

        preactx2 = tensor.dot(h1, Ux_nl)+bx_nl
        preactx2 *= r2
        preactx2 += tensor.dot(ctx_, Wcx)

        #
        # # x = tensor.matrix('temp_x', dtype='int64')
        # x_printed = theano.printing.Print('this is a very important value')(context_mask)
        # f_with_print = theano.function([context_mask], x_printed)
        # assert numpy.all( f_with_print([[5,3],[3,3]]))

        h2 = tensor.tanh(preactx2)

        h2 = u2 * h1 + (1. - u2) * h2
        h2 = m_[:, None] * h2 + (1. - m_)[:, None] * h1

        #
        # # x = tensor.matrix('temp_x', dtype='int64')
        # x_printed = theano.printing.Print('this is a very important value')(context_mask)
        # f_with_print = theano.function([context_mask], x_printed)
        # assert numpy.all( f_with_print([[6,3],[3,3]]))

        return h2, ctx_, alpha.T  # pstate_, preact, preactx, r, u


    #
    # # x = tensor.matrix('temp_x', dtype='int64')
    # x_printed = theano.printing.Print('this is a very important value')(context_mask)
    # f_with_print = theano.function([context_mask], x_printed)
    # assert numpy.all( f_with_print([[7,3],[3,3]]))

    #
    # chunking slice
    #
    def _chunk_step_decode(chunk_m_,  chunk_x_, chunk_xx_,  # seq
                          h_chunk, ctx_chunk, alpha_chunk, # output_info
                          pctx_chunk, cc,
                          U_chunk, Wc_chunk, W_comb_att_chunk, U_att_chunk, c_tt_chunk,
                          Ux_chunk, Wcx_chunk, U_nl_chunk, Ux_nl_chunk, b_nl_chunk, bx_nl_chunk):


        preact1 = tensor.dot(h_chunk, U_chunk)
        preact1 += chunk_x_
        preact1 = tensor.nnet.sigmoid(preact1)

        r1 = _slice(preact1, 0, dim)
        u1 = _slice(preact1, 1, dim)

        preactx1 = tensor.dot(h_chunk, Ux_chunk)
        preactx1 *= r1
        preactx1 += chunk_xx_

        h1 = tensor.tanh(preactx1)

        h1 = u1 * h_chunk + (1. - u1) * h1
        h1 = chunk_m_[:, None] * h1 + (1. - chunk_m_)[:, None] * h_chunk

        # attention
        pstate_ = tensor.dot(h1, W_comb_att_chunk)
        pctx__ = pctx_chunk + pstate_[None, :, :]
        #pctx__ += xc_
        pctx__ = tensor.tanh(pctx__)
        alpha = tensor.dot(pctx__, U_att_chunk)+c_tt_chunk
        alpha = alpha.reshape([alpha.shape[0], alpha.shape[1]])
        alpha = tensor.exp(alpha)
        if context_mask:
            alpha = alpha * context_mask
        alpha = alpha / alpha.sum(0, keepdims=True)
        ctx_ = (cc * alpha[:, :, None]).sum(0)  # current context

        preact2 = tensor.dot(h1, U_nl_chunk)+b_nl_chunk
        preact2 += tensor.dot(ctx_, Wc_chunk)
        preact2 = tensor.nnet.sigmoid(preact2)

        r2 = _slice(preact2, 0, dim)
        u2 = _slice(preact2, 1, dim)

        preactx2 = tensor.dot(h1, Ux_nl_chunk)+bx_nl_chunk
        preactx2 *= r2
        preactx2 += tensor.dot(ctx_, Wcx_chunk)

        h2 = tensor.tanh(preactx2)

        h2 = u2 * h1 + (1. - u2) * h2
        h2 = chunk_m_[:, None] * h2 + (1. - chunk_m_)[:, None] * h1


        return h2, ctx_, alpha.T  # chunk_word retval, pstate_, preact, preactx, r, u



    #
    # # x = tensor.matrix('temp_x', dtype='int64')
    # x_printed = theano.printing.Print('this is a very important value')(context_mask)
    # f_with_print = theano.function([context_mask], x_printed)
    # assert numpy.all( f_with_print([[8,3],[3,3]]))
    #

    #
    # chunking slice
    #
    def _chunk_step_slice(chunk_m_, cw_m_,  chunk_x_, chunk_xx_, cw_x_, cw_xx_,  # seq
                          h_chunk, ctx_chunk, alpha_chunk, h_cw, ctx_cw, alpha_cw,  # output_info
                          pctx_chunk, pctx_cw, cc,
                          U_chunk, Wc_chunk, W_comb_att_chunk, U_att_chunk, c_tt_chunk,
                          Ux_chunk, Wcx_chunk, U_nl_chunk, Ux_nl_chunk, b_nl_chunk, bx_nl_chunk,
                          U, Wc, W_comb_att, U_att, c_tt, Ux, Wcx, U_nl, Ux_nl, b_nl, bx_nl):


        #
        # # x = tensor.matrix('temp_x', dtype='int64')
        # x_printed = theano.printing.Print('this is a very important value')(context_mask)
        # f_with_print = theano.function([context_mask], x_printed)
        # assert numpy.all( f_with_print([[11,3],[3,3]]))


        preact1 = tensor.dot(h_chunk, U_chunk)
        preact1 += chunk_x_
        preact1 = tensor.nnet.sigmoid(preact1)

        r1 = _slice(preact1, 0, dim)
        u1 = _slice(preact1, 1, dim)

        preactx1 = tensor.dot(h_chunk, Ux_chunk)
        preactx1 *= r1
        preactx1 += chunk_xx_

        h1 = tensor.tanh(preactx1)


        h1 = u1 * h_chunk + (1. - u1) * h1


        h1 = chunk_m_[:, None] * h1 + (1. - chunk_m_)[:, None] * h_chunk

        #
        # # x = tensor.matrix('temp_x', dtype='int64')
        # x_printed = theano.printing.Print('this is a very important value')(context_mask)
        # f_with_print = theano.function([context_mask], x_printed)
        # assert numpy.all( f_with_print([[12,3],[3,3]]))


        # attention
        pstate_ = tensor.dot(h1, W_comb_att_chunk)
        pctx__ = pctx_chunk + pstate_[None, :, :]
        #pctx__ += xc_
        pctx__ = tensor.tanh(pctx__)
        alpha = tensor.dot(pctx__, U_att_chunk)+c_tt_chunk
        alpha = alpha.reshape([alpha.shape[0], alpha.shape[1]])
        alpha = tensor.exp(alpha)
        if context_mask:
            alpha = alpha * context_mask
        alpha = alpha / alpha.sum(0, keepdims=True)
        ctx_ = (cc * alpha[:, :, None]).sum(0)  # current context

        #
        # # x = tensor.matrix('temp_x', dtype='int64')
        # x_printed = theano.printing.Print('this is a very important value')(context_mask)
        # f_with_print = theano.function([context_mask], x_printed)
        # assert numpy.all( f_with_print([[13,3],[3,3]]))


        preact2 = tensor.dot(h1, U_nl_chunk)+b_nl_chunk
        preact2 += tensor.dot(ctx_, Wc_chunk)
        preact2 = tensor.nnet.sigmoid(preact2)

        r2 = _slice(preact2, 0, dim)
        u2 = _slice(preact2, 1, dim)

        preactx2 = tensor.dot(h1, Ux_nl_chunk)+bx_nl_chunk
        preactx2 *= r2
        preactx2 += tensor.dot(ctx_, Wcx_chunk)

        h2 = tensor.tanh(preactx2)

        h2 = u2 * h1 + (1. - u2) * h2
        h2 = chunk_m_[:, None] * h2 + (1. - chunk_m_)[:, None] * h1




        seqs = [cw_m_, cw_x_, cw_xx_]
        #seqs = [mask, state_below_, state_belowx, state_belowc]
        _step = _step_slice


        #
        # # x = tensor.matrix('temp_x', dtype='int64')
        # x_printed = theano.printing.Print('this is a very important value')(context_mask)
        # f_with_print = theano.function([context_mask], x_printed)
        # assert numpy.all( f_with_print([[14,3],[3,3]]))



        # shared_vars = [tparams[_p(prefix, 'U')],
        #            tparams[_p(prefix, 'Wc')],
        #            tparams[_p(prefix, 'W_comb_att')],
        #            tparams[_p(prefix, 'U_att')],
        #            tparams[_p(prefix, 'c_tt')],
        #            tparams[_p(prefix, 'Ux')],
        #            tparams[_p(prefix, 'Wcx')],
        #            tparams[_p(prefix, 'U_nl')],
        #            tparams[_p(prefix, 'Ux_nl')],
        #            tparams[_p(prefix, 'b_nl')],
        #            tparams[_p(prefix, 'bx_nl')]]

        # if one_step:
        #     rval = _step(*(seqs + [init_state, None, None, pctx_, context] +
        #                shared_vars))
        # else:
        rval_chunk_words, updates = theano.scan(_step,
                                    sequences=seqs,
                                    outputs_info=[h_cw[-1],
                                                  ctx_cw[-1],
                                                  alpha_cw[-1]],
                                    non_sequences=[pctx_cw, cc]+[U, Wc, W_comb_att, U_att, c_tt, Ux, Wcx, U_nl, Ux_nl, b_nl, bx_nl],
                                    name=_p(prefix, '_layers'),
                                    n_steps=n_chunk_word_step,
                                    profile=profile,
                                    strict=True)

        #
        # # x = tensor.matrix('temp_x', dtype='int64')
        # x_printed = theano.printing.Print('this is a very important value')(context_mask)
        # f_with_print = theano.function([context_mask], x_printed)
        # assert numpy.all( f_with_print([[15,3],[3,3]]))


        return h2, ctx_, alpha.T, rval_chunk_words[0], rval_chunk_words[1], rval_chunk_words[2]   # chunk_word retval, pstate_, preact, preactx, r, u





    _step = _chunk_step_slice
    #

    word_shared_vars = [tparams[_p(prefix, 'U')],
           tparams[_p(prefix, 'Wc')],
           tparams[_p(prefix, 'W_comb_att')],
           tparams[_p(prefix, 'U_att')],
           tparams[_p(prefix, 'c_tt')],
           tparams[_p(prefix, 'Ux')],
           tparams[_p(prefix, 'Wcx')],
           tparams[_p(prefix, 'U_nl')],
           tparams[_p(prefix, 'Ux_nl')],
           tparams[_p(prefix, 'b_nl')],
           tparams[_p(prefix, 'bx_nl')]]

    chunk_shared_vars = [tparams[_p(prefix, 'U_chunk')],
                   tparams[_p(prefix, 'Wc_chunk')],
                   tparams[_p(prefix, 'W_comb_att_chunk')],
                   tparams[_p(prefix, 'U_att_chunk')],
                   tparams[_p(prefix, 'c_tt_chunk')],
                   tparams[_p(prefix, 'Ux_chunk')],
                   tparams[_p(prefix, 'Wcx_chunk')],
                   tparams[_p(prefix, 'U_nl_chunk')],
                   tparams[_p(prefix, 'Ux_nl_chunk')],
                   tparams[_p(prefix, 'b_nl_chunk')],
                   tparams[_p(prefix, 'bx_nl_chunk')]]

    if one_step_chunk:

        # shared_vars = [tparams[_p(prefix, 'U_chunk')],
        #                tparams[_p(prefix, 'Wc_chunk')],
        #                tparams[_p(prefix, 'W_comb_att_chunk')],
        #                tparams[_p(prefix, 'U_att_chunk')],
        #                tparams[_p(prefix, 'c_tt_chunk')],
        #                tparams[_p(prefix, 'Ux_chunk')],
        #                tparams[_p(prefix, 'Wcx_chunk')],
        #                tparams[_p(prefix, 'U_nl_chunk')],
        #                tparams[_p(prefix, 'Ux_nl_chunk')],
        #                tparams[_p(prefix, 'b_nl_chunk')],
        #                tparams[_p(prefix, 'bx_nl_chunk')]]


        # chunk pctx
        chunk_pctx_ = tensor.dot(context, tparams[_p(prefix, 'Wc_att_chunk')]) + \
                  tparams[_p(prefix, 'b_att_chunk')]

        # projected x
        chunk_state_belowx = tensor.dot(chunk_emb, tparams[_p(prefix, 'Wx_chunk')]) +\
            tparams[_p(prefix, 'bx_chunk')]
        chunk_state_below_ = tensor.dot(chunk_emb, tparams[_p(prefix, 'W_chunk')]) +\
            tparams[_p(prefix, 'b_chunk')]



        seqs = [chunk_mask, chunk_state_below_, chunk_state_belowx]
        rval = _chunk_step_decode(*(seqs + [init_state_chunk, None, None, chunk_pctx_, context] +
                       chunk_shared_vars))
        return rval[0], rval[1], rval[2], None, None, None

    elif one_step_word:

         # word pctx
        pctx_ = tensor.dot(context, tparams[_p(prefix, 'Wc_att')]) + \
            tparams[_p(prefix, 'b_att')]

        # projected x
        # TODO make sure that the tensor multiplication with matrix ?
        state_belowx = tensor.dot(emb, tparams[_p(prefix, 'Wx')]) +\
            tparams[_p(prefix, 'bx')]
        state_below_ = tensor.dot(emb, tparams[_p(prefix, 'W')]) +\
            tparams[_p(prefix, 'b')]


        seqs = [chunk_word_mask, state_below_, state_belowx]
        # chunk_words_shared_vars = [tparams[_p(prefix, 'U')],
        #            tparams[_p(prefix, 'Wc')],
        #            tparams[_p(prefix, 'W_comb_att')],
        #            tparams[_p(prefix, 'U_att')],
        #            tparams[_p(prefix, 'c_tt')],
        #            tparams[_p(prefix, 'Ux')],
        #            tparams[_p(prefix, 'Wcx')],
        #            tparams[_p(prefix, 'U_nl')],
        #            tparams[_p(prefix, 'Ux_nl')],
        #            tparams[_p(prefix, 'b_nl')],
        #            tparams[_p(prefix, 'bx_nl')]]

        rval = _step_slice(*(seqs + [init_state_chunk_words, None, None, pctx_, context] +
                       word_shared_vars))
        return rval[0], rval[1], rval[2], None, None, None


    # word pctx
    pctx_ = tensor.dot(context, tparams[_p(prefix, 'Wc_att')]) + \
        tparams[_p(prefix, 'b_att')]

    # chunk pctx
    chunk_pctx_ = tensor.dot(context, tparams[_p(prefix, 'Wc_att_chunk')]) + \
              tparams[_p(prefix, 'b_att_chunk')]



    # projected x
    state_belowx = tensor.dot(emb, tparams[_p(prefix, 'Wx')]) +\
        tparams[_p(prefix, 'bx')]
    state_below_ = tensor.dot(emb, tparams[_p(prefix, 'W')]) +\
        tparams[_p(prefix, 'b')]


    # projected x
    chunk_state_belowx = tensor.dot(chunk_emb, tparams[_p(prefix, 'Wx_chunk')]) +\
        tparams[_p(prefix, 'bx_chunk')]
    chunk_state_below_ = tensor.dot(chunk_emb, tparams[_p(prefix, 'W_chunk')]) +\
        tparams[_p(prefix, 'b_chunk')]


    seqs = [chunk_mask, chunk_word_mask, chunk_state_below_, chunk_state_belowx,
            state_below_, state_belowx]
    #
    #
    # # x = tensor.matrix('temp_x', dtype='int64')
    # x_printed = theano.printing.Print('this is a very important value')(init_state_chunk_words.shape)
    # f_with_print = theano.function([init_state_chunk_words], x_printed)
    # assert numpy.all( f_with_print([[10,3],[3,3]]))


    # shared_vars = [tparams[_p(prefix, 'U_chunk')],
    #                tparams[_p(prefix, 'Wc_chunk')],
    #                tparams[_p(prefix, 'W_comb_att_chunk')],
    #                tparams[_p(prefix, 'U_att_chunk')],
    #                tparams[_p(prefix, 'c_tt_chunk')],
    #                tparams[_p(prefix, 'Ux_chunk')],
    #                tparams[_p(prefix, 'Wcx_chunk')],
    #                tparams[_p(prefix, 'U_nl_chunk')],
    #                tparams[_p(prefix, 'Ux_nl_chunk')],
    #                tparams[_p(prefix, 'b_nl_chunk')],
    #                tparams[_p(prefix, 'bx_nl_chunk')]]

    rval, updates = theano.scan(_step,
                                sequences=seqs,
                                outputs_info=[init_state_chunk,
                                              tensor.alloc(0., n_samples,
                                                           context.shape[2]),
                                              tensor.alloc(0., n_samples,
                                                           context.shape[0]),
                                              tensor.tile(init_state_chunk_words.reshape([1, init_state_chunk_words.shape[0], init_state_chunk_words.shape[1]]), (n_chunk_word_step, 1, 1)),
                                              tensor.alloc(0., n_chunk_word_step, n_samples,
                                                           context.shape[2]),
                                              tensor.alloc(0., n_chunk_word_step, n_samples,
                                                           context.shape[0])],
                                non_sequences=[chunk_pctx_, pctx_, context]+chunk_shared_vars+word_shared_vars,
                                name=_p(prefix, '_layers'),
                                #n_steps=n_chunk_step,
                                n_steps=n_chunk_step,
                                profile=profile,
                                strict=True)

    #
    # # x = tensor.matrix('temp_x', dtype='int64')
    # x_printed = theano.printing.Print('this is a very important value')(context_mask)
    # f_with_print = theano.function([context_mask], x_printed)
    # assert numpy.all( f_with_print([[16,3],[3,3]]))

    return rval


# initialize all parameters
def init_params(options):
    params = OrderedDict()

    # embedding
    params['Wemb'] = norm_weight(options['n_words_src'], options['dim_word'])
    params['Wemb_chunk'] = norm_weight(options['n_chunks'], options['dim_chunk'])

    params['Wemb_dec'] = norm_weight(options['n_words'], options['dim_word'])

    # encoder: bidirectional RNN
    params = get_layer(options['encoder'])[0](options, params,
                                              prefix='encoder',
                                              nin=options['dim_word'],
                                              dim=options['dim'])
    params = get_layer(options['encoder'])[0](options, params,
                                              prefix='encoder_r',
                                              nin=options['dim_word'],
                                              dim=options['dim'])
    ctxdim = 2 * options['dim']

    # init_state, init_cell
    params = get_layer('ff')[0](options, params, prefix='ff_state_chunk',
                                nin=ctxdim, nout=options['dim'])


    # init_state, init_cell
    params = get_layer('ff')[0](options, params, prefix='ff_state_chunk_words',
                                nin=ctxdim, nout=options['dim'])

    # decoder
    params = get_layer(options['decoder'])[0](options, params,
                                              prefix='decoder',
                                              nin=options['dim_word'],
                                              dim=options['dim'],
                                              dimctx=ctxdim,
                                              nin_chunk=options['dim_chunk'])
    # readout
    params = get_layer('ff')[0](options, params, prefix='ff_logit_lstm',
                                nin=options['dim'], nout=options['dim_word'],
                                ortho=False)
    params = get_layer('ff')[0](options, params, prefix='ff_logit_prev',
                                nin=options['dim_word'],
                                nout=options['dim_word'], ortho=False)
    params = get_layer('ff')[0](options, params, prefix='ff_logit_ctx',
                                nin=ctxdim, nout=options['dim_word'],
                                ortho=False)
    # params = get_layer('ff')[0](options, params, prefix='ff_logit_chunk_hidden',
    #                             nin=ctxdim, nout=options['dim_word'],
    #                             ortho=False)
    params = get_layer('ff')[0](options, params, prefix='ff_logit',
                                nin=options['dim_word'],
                                nout=options['n_words'])

    # readout

    params = get_layer('ff')[0](options, params, prefix='ff_logit_lstm_chunk',
                                nin=options['dim'], nout=options['dim_chunk'],
                                ortho=False)
    params = get_layer('ff')[0](options, params, prefix='ff_logit_prev_chunk',
                                nin=options['dim_chunk'],
                                nout=options['dim_chunk'], ortho=False)
    params = get_layer('ff')[0](options, params, prefix='ff_logit_ctx_chunk',
                                nin=ctxdim, nout=options['dim_chunk'],
                                ortho=False)

    params = get_layer('ff')[0](options, params, prefix='ff_logit_chunk',
                                nin=options['dim_chunk'],
                                nout=options['n_chunks'])

    return params


# build a training model
def build_model(tparams, options):
    opt_ret = dict()

    trng = RandomStreams(1234)
    use_noise = theano.shared(numpy.float32(0.))

    # description string: #words x #samples
    x = tensor.matrix('x', dtype='int64')
    x_mask = tensor.matrix('x_mask', dtype='float32')

    y_chunk = tensor.matrix('y_chunk', dtype='int64')
    y_chunk_words = tensor.tensor3('y_chunk_words', dtype='int64')
    y_chunk_mask = tensor.matrix('y_chunk_mask', dtype='float32')
    y_chunk_words_mask = tensor.tensor3('y_chunk_words_mask', dtype='float32')

    # for the backward rnn, we just need to invert x and x_mask
    xr = x[::-1]
    xr_mask = x_mask[::-1]

    n_timesteps = x.shape[0]
    n_timesteps_chunk = y_chunk.shape[0]
    n_timesteps_chunk_words = y_chunk_words.shape[1]
    n_samples = x.shape[1]

    # word embedding for forward rnn (source)
    emb = tparams['Wemb'][x.flatten()]
    emb = emb.reshape([n_timesteps, n_samples, options['dim_word']])
    proj = get_layer(options['encoder'])[1](tparams, emb, options,
                                            prefix='encoder',
                                            mask=x_mask)
    # word embedding for backward rnn (source)
    embr = tparams['Wemb'][xr.flatten()]
    embr = embr.reshape([n_timesteps, n_samples, options['dim_word']])
    projr = get_layer(options['encoder'])[1](tparams, embr, options,
                                             prefix='encoder_r',
                                             mask=xr_mask)

    # context will be the concatenation of forward and backward rnns
    ctx = concatenate([proj[0], projr[0][::-1]], axis=proj[0].ndim-1)

    # mean of the context (across time) will be used to initialize decoder rnn
    ctx_mean = (ctx * x_mask[:, :, None]).sum(0) / x_mask.sum(0)[:, None]

    # or you can use the last state of forward + backward encoder rnns
    # ctx_mean = concatenate([proj[0][-1], projr[0][-1]], axis=proj[0].ndim-2)

    # initial decoder state for both
    init_state_chunk = get_layer('ff')[1](tparams, ctx_mean, options,
                                    prefix='ff_state_chunk', activ='tanh')
    init_state_chunk_words = get_layer('ff')[1](tparams, ctx_mean, options,
                                    prefix='ff_state_chunk_words', activ='tanh')

    # word embedding (target), we will shift the target sequence one time step
    # to the right. This is done because of the bi-gram connections in the
    # readout and decoder rnn. The first target will be all zeros and we will
    # not condition on the last output.


    # shift the word embeddings in the chunk
    emb = tparams['Wemb_dec'][y_chunk_words.flatten()]
    emb = emb.reshape([n_timesteps_chunk, n_timesteps_chunk_words, n_samples, options['dim_word']])

    # shift the word embeddings
    def _step_shift(emb_i, e):

        emb_shifted_i = tensor.zeros_like(emb_i)
        emb_shifted_i = tensor.set_subtensor(emb_shifted_i[1:], emb_i[:-1])
        return emb_shifted_i

    # prepare scan arguments
    seqs = [emb]
    init_states = [ tensor.zeros_like(emb[0])]
    _step = _step_shift
    nsteps = emb.shape[0]

    emb_shifted, updates = theano.scan(_step,
                                sequences=seqs,
                                outputs_info=init_states,
                                n_steps=nsteps,
                                profile=profile,
                                strict=True)

    emb = emb_shifted


    # shift the chunk embeddings
    chunk_emb = tparams['Wemb_chunk'][y_chunk.flatten()]
    chunk_emb = chunk_emb.reshape([n_timesteps_chunk, n_samples, options['dim_chunk']])

    chunk_emb_shifted = tensor.zeros_like(chunk_emb)
    chunk_emb_shifted = tensor.set_subtensor(chunk_emb_shifted[1:], chunk_emb[:-1])
    chunk_emb = chunk_emb_shifted

    # TODO note the shift embedding of the word embedding $emb
    # decoder - pass through the decoder conditional gru with attention




    proj = get_layer(options['decoder'])[1](tparams, emb, chunk_emb, options,
                                            prefix='decoder',
                                            chunk_mask=y_chunk_mask,
                                            chunk_word_mask=y_chunk_words_mask,
                                            context=ctx,
                                            context_mask=x_mask,
                                            init_state_chunk=init_state_chunk,
                                            init_state_chunk_words=init_state_chunk_words,
                                            n_chunk_step=n_timesteps_chunk,
                                            n_chunk_word_step=n_timesteps_chunk_words)

    # predict the chunk

    proj_h = proj[0]

    # weighted averages of context, generated by attention module
    ctxs = proj[1]

    # weights (alignment matrix)
    opt_ret['dec_alphas_chunk'] = proj[2]


    #
    # x = tensor.matrix('temp_x', dtype='int64')
    x_printed = theano.printing.Print('proj_h ')(proj_h.shape)
    f_with_print = theano.function([proj_h], x_printed)
    assert numpy.all( f_with_print([[[1,2]],[[2,4]]]))


    # compute word probabilities
    logit_lstm_chunk = get_layer('ff')[1](tparams, proj_h, options,
                                    prefix='ff_logit_lstm_chunk', activ='linear')
    logit_prev_chunk = get_layer('ff')[1](tparams, chunk_emb, options,
                                    prefix='ff_logit_prev_chunk', activ='linear')
    logit_ctx_chunk = get_layer('ff')[1](tparams, ctxs, options,
                                   prefix='ff_logit_ctx_chunk', activ='linear')



    logit_chunk = tensor.tanh(logit_lstm_chunk+logit_prev_chunk+logit_ctx_chunk)
    if options['use_dropout']:
        logit_chunk = dropout_layer(logit_chunk, use_noise, trng)
    logit_chunk = get_layer('ff')[1](tparams, logit_chunk, options,
                               prefix='ff_logit_chunk', activ='linear')
    logit_shp_chunk = logit_chunk.shape
    probs_chunk = tensor.nnet.softmax(logit_chunk.reshape([logit_shp_chunk[0]*logit_shp_chunk[1],
                                               logit_shp_chunk[2]]))

    # cost
    y_flat_chunk = y_chunk.flatten()
    y_flat_idx_chunk = tensor.arange(y_flat_chunk.shape[0]) * options['n_chunks'] + y_flat_chunk
    cost = -tensor.log(probs_chunk.flatten()[y_flat_idx_chunk])
    cost = cost.reshape([y_chunk.shape[0], y_chunk.shape[1]])


    # predict the words!

    # hidden states of the decoder gru
    proj_h_cw = proj[3]

    # weighted averages of context, generated by attention module
    ctxs_cw = proj[4]

    # weights (alignment matrix)
    opt_ret['dec_alphas_cw'] = proj[5]

    # compute word probabilities
    logit_lstm_cw = get_layer('ff')[1](tparams, proj_h_cw, options,
                                    prefix='ff_logit_lstm', activ='linear')
    logit_prev_cw = get_layer('ff')[1](tparams, emb, options,
                                    prefix='ff_logit_prev', activ='linear')
    logit_ctx_cw = get_layer('ff')[1](tparams, ctxs_cw, options,
                                   prefix='ff_logit_ctx', activ='linear')
    logit_cw = tensor.tanh(logit_lstm_cw+logit_prev_cw+logit_ctx_cw)
    if options['use_dropout']:
        logit_cw = dropout_layer(logit_cw, use_noise, trng)
    logit_cw = get_layer('ff')[1](tparams, logit_cw, options,
                               prefix='ff_logit', activ='linear')
    logit_shp_cw = logit_cw.shape
    probs_cw = tensor.nnet.softmax(logit_cw.reshape([logit_shp_cw[0]*logit_shp_cw[1]*logit_shp_cw[2],
                                               logit_shp_cw[3]]))

    # cost
    y_flat_cw = y_chunk_words.flatten()
    y_flat_idx_cw = tensor.arange(y_flat_cw.shape[0]) * options['n_words'] + y_flat_cw

    cost_cw = -tensor.log(probs_cw.flatten()[y_flat_idx_cw])
    cost_cw = cost_cw.reshape([y_chunk_words.shape[0], y_chunk_words.shape[1], y_chunk_words.shape[2]])
    cost_cw = (cost_cw * y_chunk_words_mask).sum(1)

    cost = cost + cost_cw
    cost = (cost * y_chunk_mask).sum(0)

    return trng, use_noise, x, x_mask, y_chunk, y_chunk_mask, y_chunk_words, \
           y_chunk_words_mask, opt_ret, cost

# build a sampler
def build_sampler(tparams, options, trng, use_noise):


    x = tensor.matrix('x', dtype='int64')
    x_mask = tensor.matrix('x_mask', dtype='float32')

    # y_chunk = tensor.matrix('y_chunk', dtype='int64')
    # y_chunk_words = tensor.matrix('y_chunk_words', dtype='int64')

    # for the backward rnn, we just need to invert x and x_mask
    xr = x[::-1]

    n_timesteps = x.shape[0]
    n_samples = x.shape[1]

    # word embedding (source), forward and backward
    emb = tparams['Wemb'][x.flatten()]
    emb = emb.reshape([n_timesteps, n_samples, options['dim_word']])
    embr = tparams['Wemb'][xr.flatten()]
    embr = embr.reshape([n_timesteps, n_samples, options['dim_word']])

    # encoder
    proj = get_layer(options['encoder'])[1](tparams, emb, options,
                                            prefix='encoder')
    projr = get_layer(options['encoder'])[1](tparams, embr, options,
                                             prefix='encoder_r')

    # concatenate forward and backward rnn hidden states
    ctx = concatenate([proj[0], projr[0][::-1]], axis=proj[0].ndim-1)

    # get the input for decoder rnn initializer mlp
    ctx_mean = ctx.mean(0)
    # ctx_mean = concatenate([proj[0][-1],projr[0][-1]], axis=proj[0].ndim-2)

    # initial decoder state for both
    init_state_chunk = get_layer('ff')[1](tparams, ctx_mean, options,
                                    prefix='ff_state_chunk', activ='tanh')
    init_state_chunk_words = get_layer('ff')[1](tparams, ctx_mean, options,
                                    prefix='ff_state_chunk_words', activ='tanh')


    print 'Building f_init...',
    outs = [init_state_chunk, init_state_chunk_words, ctx]
    f_init = theano.function([x], outs, name='f_init', profile=profile)
    print 'Done'



    # TODO note that here the y_chunk and y_chunk_words are both vector, because it only conduct one steps!
    y_chunk = tensor.vector('y_sample_chunk', dtype='int64')
    y_chunk_words = tensor.vector('y_sample_chunk_words', dtype='int64')

    init_state_chunk = tensor.matrix('init_state', dtype='float32')
    init_state_chunk_words = tensor.matrix('init_state', dtype='float32')

    # if it's the first word, emb should be all zero and it is indicated by -1
    emb_chunk = tensor.switch(y_chunk[:, None] < 0,
                        tensor.alloc(0., 1, tparams['Wemb_chunk'].shape[1]),
                        tparams['Wemb_chunk'][y_chunk])
    emb_chunk_word = tensor.switch(y_chunk_words[:, None] < 0,
                        tensor.alloc(0., 1, tparams['Wemb_dec'].shape[1]),
                        tparams['Wemb_dec'][y_chunk_words])

    # apply one step of conditional gru with attention
    proj_chunk = get_layer(options['decoder'])[1](tparams, None, emb_chunk,  options,
                                            prefix='decoder',
                                            chunk_mask=None,
                                            chunk_word_mast=None,context=ctx,
                                            one_step_word=False,
                                            one_step_chunk=True,
                                            init_state_chunk=init_state_chunk,
                                            init_state_chunk_words=None)



    # apply one step of conditional gru with attention
    proj_word = get_layer(options['decoder'])[1](tparams, emb_chunk_word, None,  options,
                                            prefix='decoder',
                                            chunk_mask=None,
                                            chunk_word_mast=None,context=ctx,
                                            one_step_word=True,
                                            one_step_chunk=False,
                                            init_state_chunk=None,
                                            init_state_chunk_words=init_state_chunk_words)





    # begin to get the probability vectors

    proj_h = proj_chunk[0]

    # weighted averages of context, generated by attention module
    ctxs =  proj_chunk[1]

    # compute word probabilities
    logit_lstm_chunk = get_layer('ff')[1](tparams, proj_h, options,
                                    prefix='ff_logit_lstm_chunk', activ='linear')
    logit_prev_chunk = get_layer('ff')[1](tparams, emb_chunk, options,
                                    prefix='ff_logit_prev_chunk', activ='linear')
    logit_ctx_chunk = get_layer('ff')[1](tparams, ctxs, options,
                                   prefix='ff_logit_ctx_chunk', activ='linear')
    logit_chunk = tensor.tanh(logit_lstm_chunk+logit_prev_chunk+logit_ctx_chunk)
    if options['use_dropout']:
        logit_chunk = dropout_layer(logit_chunk, use_noise, trng)
    logit_chunk = get_layer('ff')[1](tparams, logit_chunk, options,
                               prefix='ff_logit_chunk', activ='linear')
    probs_chunk = tensor.nnet.softmax(logit_chunk)
    next_sample_chunk = trng.multinomial(pvals=probs_chunk).argmax(1)



    # predict the words!

    # hidden states of the decoder gru
    proj_h_cw = proj_word[0]

    # weighted averages of context, generated by attention module
    ctxs_cw = proj_word[1]

    # compute word probabilities
    logit_lstm_cw = get_layer('ff')[1](tparams, proj_h_cw, options,
                                    prefix='ff_logit_lstm', activ='linear')
    logit_prev_cw = get_layer('ff')[1](tparams, emb_chunk_word, options,
                                    prefix='ff_logit_prev', activ='linear')
    logit_ctx_cw = get_layer('ff')[1](tparams, ctxs_cw, options,
                                   prefix='ff_logit_ctx', activ='linear')
    logit_cw = tensor.tanh(logit_lstm_cw+logit_prev_cw+logit_ctx_cw)
    if options['use_dropout']:
        logit_cw = dropout_layer(logit_cw, use_noise, trng)
    logit_cw = get_layer('ff')[1](tparams, logit_cw, options,
                               prefix='ff_logit', activ='linear')
    probs_cw = tensor.nnet.softmax(logit_cw)
    next_sample_cw = trng.multinomial(pvals=probs_cw).argmax(1)

    # sample from softmax distribution to get the sample

    # compile a function to do the whole thing above, next word probability,
    # sampled word for the next target, next hidden state to be used
    print 'Building f_next..',
    inps = [y_chunk, ctx, init_state_chunk]
    outs = [probs_chunk, next_sample_chunk, proj_h]
    f_next_chunk = theano.function(inps, outs, name='f_next_chunk', profile=profile)
    inps = [y_chunk_words, ctx, init_state_chunk_words]
    outs = [probs_cw, next_sample_cw, proj_h_cw]
    f_next_chunk_word = theano.function(inps, outs, name='f_next_chunk_word', profile=profile)
    print 'Done'

    return f_init, f_next_chunk, f_next_chunk_word

# generate sample, either with stochastic sampling or beam search. Note that,
# this function iteratively calls f_init and f_next functions.
def gen_sample(tparams, f_init, f_next_chunk, f_next_word, x,
               options, trng=None, k_chunk=1, k_word=1, maxlen_words=10,
               maxlen_chunks=10,
               stochastic=True, argmax=False):

    # k is the beam size we have
    if k_chunk > 1 or k_word > 1:
        assert not stochastic, \
            'Beam search does not support stochastic sampling'


    # used to record the fixed item for beam search
    chunk_live_k = 1
    chunk_dead_k = 0

    word_live_k = 1
    word_dead_k = 0



    # chunk_hyp_samples = [[]] * chunk_live_k
    # chunk_hyp_scores = numpy.zeros(chunk_live_k).astype('float32')
    # chunk_hyp_states = []

    # get initial state of chunk and word decoder rnn
    ret = f_init(x)
    next_state_chunk, next_state_word, ctx0 = ret[0], ret[1], ret[2]


    next_word = -1 * numpy.ones((1,)).astype('int64')  # bos indicator
    next_chunk = -1 * numpy.ones((1,)).astype('int64')  # bos indicator


    # sample container for beam search

    final_beam_sample_word = []
    final_beam_sample_chunk = []
    final_beam_word_score = []
    final_beam_chunk_score= []
    final_beam_score = []

    beam_sample_chunk = [[]] * chunk_live_k #TODO make sure the shape of the sample
    beam_sample_word = [[[]]] * chunk_live_k

    beam_sample_chunk_score = numpy.zeros(chunk_live_k).astype('float32')
    beam_sample_word_score = [numpy.zeros(chunk_live_k).astype('float32')]

    # beam_state_chunk=next_state_chunk
    beam_word_state=[next_state_word] * chunk_live_k
    beam_next_word = [next_word] * chunk_live_k


    #
    # for max chunk iteration
    #
    for ii_chunk in xrange(maxlen_chunks):

        # get the next chunk configuration
        ctx = numpy.tile(ctx0, [chunk_live_k, 1])
        inps = [next_chunk, ctx, next_state_chunk]
        ret = f_next_chunk(*inps)
        next_p_chunk, next_chunk, next_state_chunk = ret[0], ret[1], ret[2]


        # stochastic: greedy decoding
        if stochastic:
            if argmax:
                nc = next_p_chunk[0].argmax()
            else:
                nc = next_chunk[0]
            final_beam_sample_chunk.append(nc)
            final_beam_score -= numpy.log(next_p_chunk[0, nc])

            final_beam_sample_word.append( -1 * nc)

            if nc == 0:
                break

            for ii_chunk in xrange(maxlen_words):
                ctx = numpy.tile(ctx0, [word_live_k, 1])
                inps = [next_word, ctx, next_state_word]
                ret = f_next_word(*inps)
                next_p_word, next_word, next_state_word = ret[0], ret[1], ret[2]

                if stochastic:
                    if argmax:
                        nw = next_p_word[0].argmax()
                    else:
                        nw = next_word[0]
                    final_beam_sample_word.append(nw)
                    final_beam_score -= numpy.log(next_p_word[0, nc])
                    if nw == 0:
                        break

        # beam search decoding
        # else:
        #     print

    #
    #         # get the best k candidates, by 0~vob, vob+1 ~ 2vob ...
    #
    #         chunk_cand_scores = beam_sample_chunk_score[:, None] - numpy.log(next_p_chunk)
    #         chunk_cand_flat = chunk_cand_scores.flatten()
    #         chunk_ranks_flat = chunk_cand_flat.argsort()[:(k_chunk-chunk_dead_k)]
    #
    #         chunk_voc_size = next_p_chunk.shape[1]
    #         chunk_trans_indices = chunk_ranks_flat / chunk_voc_size # index in the sample
    #         chunk_indices = chunk_ranks_flat % chunk_voc_size
    #         chunk_costs = chunk_cand_flat[chunk_ranks_flat] # get all the probability
    #
    #         new_chunk_hyp_samples = []
    #         new_chunk_hyp_scores = numpy.zeros(k_chunk-chunk_dead_k).astype('float32')
    #         new_chunk_hyp_states = []
    #
    #
    #
    #         # stores the newly generated results
    #         new_beam_sample_word = [] * chunk_live_k
    #         new_beam_sample_word_score = []
    #         new_beam_state_word=[]
    #
    #         # idx is the order of the executed chunk sequence,
    #         # and ti is the index of the parant sequence it is generated from
    #         for idx, [ti, wi] in enumerate(zip(chunk_trans_indices, chunk_indices)):
    #
    #             new_chunk_hyp_samples.append(beam_sample_chunk[ti]+[wi])
    #             new_chunk_hyp_scores[idx] = copy.copy(chunk_costs[idx])
    #             new_chunk_hyp_states.append(copy.copy(next_state_chunk[ti]))
    #
    #
    #             #============
    #             # begin to sample the possible words for each chunk
    #             # for each chunk, we predict the corresponding words
    #             #============
    #
    #             if wi == 0:
    #                 final_beam_sample_chunk.append(new_chunk_hyp_samples[idx])
    #                 final_beam_chunk_score.append(new_chunk_hyp_scores[idx])
    #
    #                 # we don't add the chunk score into the word score here.
    #                 final_beam_sample_word.extend(beam_sample_word[ti])
    #                 final_beam_word_score.extend(beam_sample_word_score[ti].tolist())
    #
    #                 final_beam_score.extend( (beam_sample_word_score[ti] + new_chunk_hyp_scores[idx]).tolist)
    #
    #                 chunk_dead_k += 1
    #
    #                 continue
    #
    #             word_live_k = 1
    #             word_dead_k = 0
    #
    #             #
    #             # # to store the word sample configurations for the chunks in the beam
    #             # word_hyp_samples = [[[]]] * word_live_k
    #             # word_hyp_scores = [numpy.zeros(word_live_k).astype('float32')]
    #             # word_hyp_states = [[]]
    #
    #             complete_word_sample = []
    #             complete_word_sample_score = []
    #             complete_word_sample_state = []
    #
    #             for ii_word in xrange(maxlen_words):
    #
    #                 ctx = numpy.tile(ctx0, [word_live_k, 1])
    #                 inps = [beam_next_word[ti], ctx, beam_word_state[ti]]
    #                 ret = f_next_word(*inps)
    #                 new_next_p_word_i, new_next_word_i, new_next_state_word_i \
    #                     = ret[0], ret[1], ret[2]
    #
    #
    #                 word_cand_scores = beam_sample_word_score[idx][:, None] - numpy.log(new_next_p_word_i)
    #                 word_cand_flat = word_cand_scores.flatten()
    #                 word_ranks_flat = word_cand_flat.argsort()[:(k_word-word_dead_k)]
    #
    #                 word_voc_size = new_next_p_word_i.shape[1]
    #                 word_trans_indices = word_ranks_flat / word_voc_size # index in the sample
    #                 word_indices = word_ranks_flat % word_voc_size
    #                 word_costs = word_cand_flat[word_ranks_flat] # get all the probability
    #
    #                 new_word_hyp_samples = []
    #                 new_word_hyp_scores = numpy.zeros(k_word-word_dead_k).astype('float32')
    #                 new_word_hyp_states = []
    #
    #                 for idx_word, [ti_word, wi_word] in enumerate(zip(word_trans_indices, word_indices)):
    #                     new_word_hyp_samples.append(beam_sample_word[ti][ti_word]+[wi_word])
    #                     new_word_hyp_scores[idx_word] = copy.copy(word_costs[idx_word])
    #                     new_word_hyp_states.append(copy.copy(beam_word_state[ti][ti_word]))
    #
    #                 # append the new config into the temp beam container
    #                 new_beam_sample_word.append(new_beam_sample_word)
    #                 new_beam_sample_word_score.append(new_word_hyp_scores)
    #                 new_beam_state_word.append(new_word_hyp_states)
    #
    #                 # check the finished samples
    #                 new_word_live_k = 0
    #                 beam_sample_word[ti] = []
    #                 beam_sample_word_score[ti] = []
    #                 beam_word_state[ti] = []
    #
    #
    #                 for idx_word in xrange(len(new_word_hyp_samples)):
    #                     if new_word_hyp_samples[idx][-1] == 0:
    #                         complete_word_sample.append(new_word_hyp_samples[idx_word])
    #                         complete_word_sample_score.append(new_word_hyp_scores[idx_word])
    #                         complete_word_sample_state.append(new_word_hyp_states[idx_word])
    #                         word_dead_k += 1
    #                     else:
    #                         new_word_live_k += 1
    #                         beam_sample_word[ti].append(new_word_hyp_samples[idx])
    #                         beam_sample_word_score[ti].append(new_word_hyp_scores[idx])
    #                         beam_word_state[ti].append(new_word_hyp_states[idx])
    #
    #
    #
    #                 beam_sample_word_score[ti] = numpy.array(beam_sample_word_score[ti])
    #                 word_live_k = new_word_live_k
    #
    #                 if word_live_k < 1:
    #                     break
    #                 if word_dead_k >= k_word:
    #                     break
    #
    #
    #                 next_word = numpy.array([w[-1] for w in beam_sample_word_score[ti]])
    #                 beam_word_state = numpy.array(beam_word_state[ti])
    #
    #             # end max word iteration
    #
    #             for widx in xrange(beam_sample_word[ti]):
    #                 complete_word_sample.append(beam_sample_word[ti][widx])
    #                 complete_word_sample_score.append(beam_sample_word_score[ti][widx])
    #                 complete_word_sample_state.append(beam_word_state[widx])
    #
    #             new_beam_state_word.append(complete_word_sample)
    #             new_beam_sample_word_score.append(complete_word_sample_score)
    #             new_beam_state_word.append(complete_word_sample_state)
    #
    #
    #             #============
    #             # end to sample max words
    #             #============
    #
    #         # end to sample possible chunks
    #
    #         beam_sample_word = new_beam_state_word
    #         beam_sample_word_score = new_beam_sample_word_score
    #         beam_word_state = new_beam_state_word
    #
    #
    #         # check the finished samples
    #         new_chunk_live_k = 0
    #         beam_sample_chunk = []
    #         beam_sample_chunk_score = []
    #         beam_chunk_states = []
    #
    #         for idx in xrange(len(new_chunk_hyp_samples)):
    #
    #             # chunk sequence ends ?
    #             if new_chunk_hyp_samples[idx][-1] == 0:
    #                 continue
    #             else:
    #                 new_chunk_live_k += 1
    #                 beam_sample_chunk.append(new_chunk_hyp_samples[idx])
    #                 beam_sample_chunk_score.append(new_chunk_hyp_scores[idx])
    #                 beam_chunk_states.append(new_chunk_hyp_states[idx])
    #         beam_sample_chunk_score = numpy.array(beam_sample_chunk_score)
    #         chunk_live_k = new_chunk_live_k
    #
    #         if chunk_live_k < 1:
    #             break
    #         if chunk_dead_k >= k_chunk:
    #             break
    #
    #         next_chunk = numpy.array([w[-1] for w in beam_sample_chunk])
    #         next_state_chunk = numpy.array(beam_chunk_states)
    #
    #
    #     # end chunk iteration
    #
    # if not stochastic:
    #     # dump every remaining one
    #     if chunk_live_k > 0:
    #         for idx in xrange(chunk_live_k):
    #             final_beam_sample_word.extend(beam_sample_word[idx])
    #             final_beam_sample_chunk.append(beam_sample_chunk[idx])
    #             final_beam_score.append((beam_sample_word_score[idx] +
    #                                      beam_sample_chunk_score[idx]).tolist)

    return final_beam_sample_word, final_beam_score


# calculate the log probablities on a given corpus using translation model
def pred_probs(f_log_probs, prepare_data, options, iterator, verbose=True):
    probs = []

    n_done = 0

    for x, y_chunk, y_cw in iterator:
        n_done += len(x)

        x, x_mask, y_c, y_mask_c, y_cw, y_mask_cw = prepare_data(x, y_chunk, y_cw,
                                            n_words_src=options['n_words_src'],
                                            n_words=options['n_words'])

        pprobs = f_log_probs(x, x_mask, y_c, y_mask_c, y_cw, y_mask_cw)
        for pp in pprobs:
            probs.append(pp)

        if numpy.isnan(numpy.mean(probs)):
            ipdb.set_trace()

        if verbose:
            print >>sys.stderr, '%d samples computed' % (n_done)

    return numpy.array(probs)


# optimizers
# name(hyperp, tparams, grads, inputs (list), cost) = f_grad_shared, f_update
def adam(lr, tparams, grads, inp, cost, beta1=0.9, beta2=0.999, e=1e-8):

    gshared = [theano.shared(p.get_value() * 0., name='%s_grad' % k)
               for k, p in tparams.iteritems()]
    gsup = [(gs, g) for gs, g in zip(gshared, grads)]

    f_grad_shared = theano.function(inp, cost, updates=gsup, profile=profile)

    updates = []

    t_prev = theano.shared(numpy.float32(0.))
    t = t_prev + 1.
    lr_t = lr * tensor.sqrt(1. - beta2**t) / (1. - beta1**t)

    for p, g in zip(tparams.values(), gshared):
        m = theano.shared(p.get_value() * 0., p.name + '_mean')
        v = theano.shared(p.get_value() * 0., p.name + '_variance')
        m_t = beta1 * m + (1. - beta1) * g
        v_t = beta2 * v + (1. - beta2) * g**2
        step = lr_t * m_t / (tensor.sqrt(v_t) + e)
        p_t = p - step
        updates.append((m, m_t))
        updates.append((v, v_t))
        updates.append((p, p_t))
    updates.append((t_prev, t))

    f_update = theano.function([lr], [], updates=updates,
                               on_unused_input='ignore', profile=profile)

    return f_grad_shared, f_update


def adadelta(lr, tparams, grads, inp, cost):
    zipped_grads = [theano.shared(p.get_value() * numpy.float32(0.),
                                  name='%s_grad' % k)
                    for k, p in tparams.iteritems()]
    running_up2 = [theano.shared(p.get_value() * numpy.float32(0.),
                                 name='%s_rup2' % k)
                   for k, p in tparams.iteritems()]
    running_grads2 = [theano.shared(p.get_value() * numpy.float32(0.),
                                    name='%s_rgrad2' % k)
                      for k, p in tparams.iteritems()]

    zgup = [(zg, g) for zg, g in zip(zipped_grads, grads)]
    rg2up = [(rg2, 0.95 * rg2 + 0.05 * (g ** 2))
             for rg2, g in zip(running_grads2, grads)]

    f_grad_shared = theano.function(inp, cost, updates=zgup+rg2up,
                                    profile=profile)

    updir = [-tensor.sqrt(ru2 + 1e-6) / tensor.sqrt(rg2 + 1e-6) * zg
             for zg, ru2, rg2 in zip(zipped_grads, running_up2,
                                     running_grads2)]
    ru2up = [(ru2, 0.95 * ru2 + 0.05 * (ud ** 2))
             for ru2, ud in zip(running_up2, updir)]
    param_up = [(p, p + ud) for p, ud in zip(itemlist(tparams), updir)]

    f_update = theano.function([lr], [], updates=ru2up+param_up,
                               on_unused_input='ignore', profile=profile)

    return f_grad_shared, f_update


def rmsprop(lr, tparams, grads, inp, cost):
    zipped_grads = [theano.shared(p.get_value() * numpy.float32(0.),
                                  name='%s_grad' % k)
                    for k, p in tparams.iteritems()]
    running_grads = [theano.shared(p.get_value() * numpy.float32(0.),
                                   name='%s_rgrad' % k)
                     for k, p in tparams.iteritems()]
    running_grads2 = [theano.shared(p.get_value() * numpy.float32(0.),
                                    name='%s_rgrad2' % k)
                      for k, p in tparams.iteritems()]

    zgup = [(zg, g) for zg, g in zip(zipped_grads, grads)]
    rgup = [(rg, 0.95 * rg + 0.05 * g) for rg, g in zip(running_grads, grads)]
    rg2up = [(rg2, 0.95 * rg2 + 0.05 * (g ** 2))
             for rg2, g in zip(running_grads2, grads)]

    f_grad_shared = theano.function(inp, cost, updates=zgup+rgup+rg2up,
                                    profile=profile)

    updir = [theano.shared(p.get_value() * numpy.float32(0.),
                           name='%s_updir' % k)
             for k, p in tparams.iteritems()]
    updir_new = [(ud, 0.9 * ud - 1e-4 * zg / tensor.sqrt(rg2 - rg ** 2 + 1e-4))
                 for ud, zg, rg, rg2 in zip(updir, zipped_grads, running_grads,
                                            running_grads2)]
    param_up = [(p, p + udn[1])
                for p, udn in zip(itemlist(tparams), updir_new)]
    f_update = theano.function([lr], [], updates=updir_new+param_up,
                               on_unused_input='ignore', profile=profile)

    return f_grad_shared, f_update


def sgd(lr, tparams, grads, x, mask, y, cost):
    gshared = [theano.shared(p.get_value() * 0.,
                             name='%s_grad' % k)
               for k, p in tparams.iteritems()]
    gsup = [(gs, g) for gs, g in zip(gshared, grads)]

    f_grad_shared = theano.function([x, mask, y], cost, updates=gsup,
                                    profile=profile)

    pup = [(p, p - lr * g) for p, g in zip(itemlist(tparams), gshared)]
    f_update = theano.function([lr], [], updates=pup, profile=profile)

    return f_grad_shared, f_update


def train(dim_word=100,  # word vector dimensionality
          dim_chunk=50,
          dim=1000,  # the number of LSTM units
          encoder='gru',
          decoder='gru_cond',
          patience=10,  # early stopping patience
          max_epochs=5000,
          finish_after=10000000,  # finish after this many updates
          dispFreq=100,
          decay_c=0.,  # L2 regularization penalty
          alpha_c=0.,  # alignment regularization
          clip_c=-1.,  # gradient clipping threshold
          lrate=0.01,  # learning rate
          n_words_src=100000,  # source vocabulary size
          n_words=100000,  # target vocabulary size
          n_chunks=1000,  # target vocabulary size
          maxlen_chunk=10,  # maximum length of the description
          maxlen_chunk_words=8,  # maximum length of the description
          optimizer='rmsprop',
          batch_size=16,
          valid_batch_size=16,
          saveto='model.npz',
          validFreq=1000,
          saveFreq=1000,   # save the parameters after every saveFreq updates
          sampleFreq=100,   # generate some samples after every sampleFreq
          datasets=[
              '/data/lisatmp3/chokyun/europarl/europarl-v7.fr-en.en.tok',
              '/data/lisatmp3/chokyun/europarl/europarl-v7.fr-en.fr.tok'],
          valid_datasets=['../data/dev/newstest2011.en.tok',
                          '../data/dev/newstest2011.fr.tok'],
          dictionaries=[
              '/data/lisatmp3/chokyun/europarl/europarl-v7.fr-en.en.tok.pkl',
              '/data/lisatmp3/chokyun/europarl/europarl-v7.fr-en.fr.tok.pkl'],
          dictionary_chunk='/data/lisatmp3/chokyun/europarl/europarl-v7.fr-en.en.tok.pkl',
          use_dropout=False,
          reload_=False,
          overwrite=False):

    # Model options
    model_options = locals().copy()

    # load the dictionaries of both source and target
    # load dictionaries and invert them
    worddicts = [None] * len(dictionaries)
    worddicts_r = [None] * len(dictionaries)
    for ii, dd in enumerate(dictionaries):
        with open(dd, 'rb') as f:
            worddicts[ii] = pkl.load(f)
        worddicts_r[ii] = dict()
        for kk, vv in worddicts[ii].iteritems():
            worddicts_r[ii][vv] = kk

    # dict for chunk label
    worddict_chunk = [None]
    worddict_r_chunk = [None]
    with open(dictionary_chunk, 'rb') as f:
        worddict_chunk = pkl.load(f)
    worddict_r_chunk = dict()
    for kk, vv in worddict_chunk.iteritems():
        worddict_r_chunk[vv] = kk
    model_options['n_chunks'] = len(worddict_chunk)

    # reload options
    if reload_ and os.path.exists(saveto):
        print 'Reloading model options'
        with open('%s.pkl' % saveto, 'rb') as f:
            model_options = pkl.load(f)

    print 'Loading data'

    # TODO add a new chunk dict here, and modify the arguments of TrainingTextIterator
    train = TrainingTextIterator(datasets[0], datasets[1],
                         dictionaries[0], dictionaries[1], dictionary_chunk,
                         n_words_source=n_words_src, n_words_target=n_words,
                         batch_size=batch_size,
                         max_chunk_len=maxlen_chunk, max_word_len=maxlen_chunk_words)
    valid = TrainingTextIterator(valid_datasets[0], valid_datasets[1],
                         dictionaries[0], dictionaries[1], dictionary_chunk,
                         n_words_source=n_words_src, n_words_target=n_words,
                         batch_size=valid_batch_size,
                         max_chunk_len=maxlen_chunk, max_word_len=maxlen_chunk_words)

    print 'Building model'
    params = init_params(model_options)
    # reload parameters
    if reload_ and os.path.exists(saveto):
        print 'Reloading model parameters'
        params = load_params(saveto, params)

    tparams = init_tparams(params)

    # modify the module of build model!
    # especially the inputs and outputs
    trng, use_noise, \
        x, x_mask, y_chunk, y_chunk_mask, y_cw, y_cw_mask,\
        opt_ret, \
        cost= \
        build_model(tparams, model_options)

    inps = [x, x_mask, y_chunk, y_chunk_mask, y_cw, y_cw_mask]

    print 'Building sampler'
    f_init, f_next_chunk, f_next_word = build_sampler(tparams, model_options, trng, use_noise)

    # before any regularizer
    print 'Building f_log_probs...',
    f_log_probs = theano.function(inps, cost, profile=profile)
    print 'Done'

    cost = cost.mean()

    # apply L2 regularization on weights
    if decay_c > 0.:
        decay_c = theano.shared(numpy.float32(decay_c), name='decay_c')
        weight_decay = 0.
        for kk, vv in tparams.iteritems():
            weight_decay += (vv ** 2).sum()
        weight_decay *= decay_c
        cost += weight_decay

    # regularize the alpha weights
    if alpha_c > 0. and not model_options['decoder'].endswith('simple'):
        alpha_c = theano.shared(numpy.float32(alpha_c), name='alpha_c')
        alpha_reg = alpha_c * (
            (tensor.cast(y_chunk_mask.sum(0)//x_mask.sum(0), 'float32')[:, None] -
             opt_ret['dec_alphas'].sum(0))**2).sum(1).mean()
        alpha_reg += alpha_c * (
            (tensor.cast(y_cw_mask.sum(0).sum(0)//x_mask.sum(0), 'float32')[:, None] -
             opt_ret['dec_alphas'].sum(0).sum(0))**2).sum(1).mean()
        cost += alpha_reg

    # after all regularizers - compile the computational graph for cost
    print 'Building f_cost...',
    f_cost = theano.function(inps, cost, profile=profile)
    print 'Done'

    print 'Computing gradient...',
    grads = tensor.grad(cost, wrt=itemlist(tparams))
    print 'Done'

    # apply gradient clipping here
    if clip_c > 0.:
        g2 = 0.
        for g in grads:
            g2 += (g**2).sum()
        new_grads = []
        for g in grads:
            new_grads.append(tensor.switch(g2 > (clip_c**2),
                                           g / tensor.sqrt(g2) * clip_c,
                                           g))
        grads = new_grads

    # compile the optimizer, the actual computational graph is compiled here
    lr = tensor.scalar(name='lr')
    print 'Building optimizers...',
    f_grad_shared, f_update = eval(optimizer)(lr, tparams, grads, inps, cost)
    print 'Done'

    print 'Optimization'

    best_p = None
    bad_counter = 0
    uidx = 0
    estop = False
    history_errs = []
    # reload history
    if reload_ and os.path.exists(saveto):
        rmodel = numpy.load(saveto)
        history_errs = list(rmodel['history_errs'])
        if 'uidx' in rmodel:
            uidx = rmodel['uidx']

    if validFreq == -1:
        validFreq = len(train[0])/batch_size
    if saveFreq == -1:
        saveFreq = len(train[0])/batch_size
    if sampleFreq == -1:
        sampleFreq = len(train[0])/batch_size

    for eidx in xrange(max_epochs):
        n_samples = 0

        for x, y_chunk, y_cw in train:
            n_samples += len(x)
            uidx += 1
            use_noise.set_value(1.)

            x, x_mask, y_c, y_mask_c, y_cw, y_mask_cw = prepare_training_data(x, y_chunk, y_cw, maxlen_chunk=maxlen_chunk, maxlen_cw=maxlen_chunk_words,
                                                n_words_src=n_words_src,
                                                n_words=n_words)

            if x is None:
                print 'Minibatch with zero sample under chunk length ', maxlen_chunk, 'word length: ', maxlen_chunk_words
                uidx -= 1
                continue

            ud_start = time.time()

            # compute cost, grads and copy grads to sh            self.target_buffer = _tcbufared variables
            cost = f_grad_shared(x, x_mask, y_c, y_mask_c, y_cw, y_mask_cw)

            print 'processed one batch'

            # do the update on parameters
            f_update(lrate)

            ud = time.time() - ud_start

            # check for bad numbers, usually we remove non-finite elements
            # and continue training - but not done here
            if numpy.isnan(cost) or numpy.isinf(cost):
                print 'NaN detected'
                return 1., 1., 1.

            # verbose
            if numpy.mod(uidx, dispFreq) == 0:
                print 'Epoch ', eidx, 'Update ', uidx, 'Cost ', cost, 'UD ', ud

            # save the best model so far, in addition, save the latest model
            # into a separate file with the iteration number for external eval
            if numpy.mod(uidx, saveFreq) == 0:
                print 'Saving the best model...',
                if best_p is not None:
                    params = best_p
                else:
                    params = unzip(tparams)
                numpy.savez(saveto, history_errs=history_errs, uidx=uidx, **params)
                pkl.dump(model_options, open('%s.pkl' % saveto, 'wb'))
                print 'Done'

                # save with uidx
                if not overwrite:
                    print 'Saving the model at iteration {}...'.format(uidx),
                    saveto_uidx = '{}.iter{}.npz'.format(
                        os.path.splitext(saveto)[0], uidx)
                    numpy.savez(saveto_uidx, history_errs=history_errs,
                                uidx=uidx, **unzip(tparams))
                    print 'Done'


            # generate some samples with the model and display them
            if numpy.mod(uidx, sampleFreq) == 0:
                # FIXME: random selection?
                for jj in xrange(numpy.minimum(5, x.shape[1])):
                    stochastic = True
                    sample, score = gen_sample(tparams, f_init, f_next_chunk, f_next_word,
                                               x[:, jj][:, None],
                                               model_options, trng=trng, k_chunk=1, k_word=1,
                                               maxlen_words=10,
               maxlen_chunks=10,
                                               stochastic=stochastic,
                                               argmax=False)
                    print 'Source ', jj, ': ',
                    for vv in x[:, jj]:
                        if vv == 0:
                            break
                        if vv in worddicts_r[0]:
                            print worddicts_r[0][vv],
                        else:
                            print 'UNK',
                    print
                    print 'Truth ', jj, ' : ',
                    ci = 0
                    # print y_chunk[: , jj]
                    for chunk_index in y_c[:, jj]:

                        if chunk_index == 0:
                            break
                        if chunk_index in worddict_r_chunk:
                            print '|', worddict_r_chunk[chunk_index],
                        for wi in y_cw[ci, :, jj]:
                            if wi == 0:
                                break
                            if wi in worddicts_r[1]:
                                print worddicts_r[1][wi],
                            else:
                                print 'UNK',
                        ci += 1
                    print
                    print 'Sample ', jj, ': ',
                    if stochastic:
                        ss = sample
                    else:
                        score = score / numpy.array([len(s) for s in sample])
                        ss = sample[score.argmin()]
                    for vv in ss:
                        if vv == 0:
                            break
                        if vv < 0:
                            vv = vv * -1
                            print '|', worddict_r_chunk[vv],
                        if vv in worddicts_r[1]:
                            print worddicts_r[1][vv],
                        else:
                            print 'UNK',
                    print

            # validate model on validation set and early stop if necessary
            if numpy.mod(uidx, validFreq) == 0:
                use_noise.set_value(0.)
                valid_errs = pred_probs(f_log_probs, prepare_training_data,
                                        model_options, valid)
                valid_err = valid_errs.mean()
                history_errs.append(valid_err)

                if uidx == 0 or valid_err <= numpy.array(history_errs).min():
                    best_p = unzip(tparams)
                    bad_counter = 0
                if len(history_errs) > patience and valid_err >= \
                        numpy.array(history_errs)[:-patience].min():
                    bad_counter += 1
                    if bad_counter > patience:
                        print 'Early Stop!'
                        estop = True
                        break

                if numpy.isnan(valid_err):
                    ipdb.set_trace()

                print 'Valid ', valid_err

            # finish after this many updates
            if uidx >= finish_after:
                print 'Finishing after %d iterations!' % uidx
                estop = True
                break

        print 'Seen %d samples' % n_samples

        if estop:
            break

    if best_p is not None:
        zipp(best_p, tparams)

    use_noise.set_value(0.)
    valid_err = pred_probs(f_log_probs, prepare_training_data,
                           model_options, valid).mean()

    print 'Valid ', valid_err

    params = copy.copy(best_p)
    numpy.savez(saveto, zipped_params=best_p,
                history_errs=history_errs,
                uidx=uidx,
                **params)

    return valid_err


if __name__ == '__main__':
    pass