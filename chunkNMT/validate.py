'''
Translates a source file using a translation model.
'''
import argparse

import numpy
import theano
import cPickle as pkl
import heapq
from translate_gpu import translate_file
import logging
import time
import subprocess
import re

from nmt import (build_model, pred_probs, load_params,
                 init_params, init_tparams, prepare_training_data)

from training_data_iterator import TrainingTextIterator

def getCost(tparams, options, model, valid):



    trng, use_noise, \
    x, x_mask, y_chunk, y_chunk_mask, y_cw, y_cw_mask, lw_in_chunk, \
    opt_ret, \
    cost= \
        build_model(tparams, options)


    inps = [x, x_mask, y_chunk, y_chunk_mask, y_cw, y_cw_mask, lw_in_chunk]



    # before any regularizer
    print 'Building f_log_probs...',
    f_log_probs = theano.function(inps, cost, profile=False)
    print 'Done'

    valid_errs = pred_probs(f_log_probs, prepare_training_data,
                                        options, valid)
    valid_err = valid_errs.mean()

    return valid_err

def getBLEU():

    return 0






def main(model,
         pklmodel,
         logfile,
         outputfile,
         bleu_scrip,
         valid_datasets=['../data/dev/newstest2011.en.tok',
                          '../data/dev/newstest2011.fr.tok'],
         dictionaries=[
              '/data/lisatmp3/chokyun/europarl/europarl-v7.fr-en.en.tok.pkl',
              '/data/lisatmp3/chokyun/europarl/europarl-v7.fr-en.fr.tok.pkl'],
         dictionary_chunk='/data/lisatmp3/chokyun/europarl/europarl-v7.fr-en.en.tok.pkl',
         beginModelIter=200000,
         k_best_keep=10):




    logfile = open(logfile, 'w')

    best_bleu = -1
    best_bleu_iter = beginModelIter

    heap = []
    heapq.heapify(heap)

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
    print worddict_chunk

    print 'load model model_options'
    with open('%s' % pklmodel, 'rb') as f:
        options = pkl.load(f)



    for iter in range(beginModelIter, 500000, 1000):

        print iter


        model_file_name = model + '.iter' + str(iter) + '.npz'


        # build valid set
        valid = TrainingTextIterator(valid_datasets[0], valid_datasets[1],
                                     dictionaries[0], dictionaries[1], dictionary_chunk,
                                     n_words_source=options['n_words_src'], n_words_target=options['n_words'],
                                     batch_size=options['batch_size'],
                                     max_chunk_len=options['maxlen_chunk'], max_word_len=options['maxlen_chunk_words'])


        # allocate model parameters
        params = init_params(options)

        # load model parameters and set theano shared variables
        params = load_params(model_file_name, params)
        tparams = init_tparams(params)

        currentIterCost = -1 * getCost(tparams, options, model_file_name, valid)

        print >> logfile, '==========================='

        print >> logfile, 'Iter ' + str(iter) + ', Cost' + str(-1 * currentIterCost)


        compute_bleu = False

        if len(heap) < k_best_keep:
            compute_bleu = True
        else:
            top_item = heap[0] # smallest in heap
            if top_item < currentIterCost: # min heap
                heapq.heappop(heap)
                compute_bleu = True


        if compute_bleu:
            heapq.heappush(heap, currentIterCost)

            print 'begin to compute BLEU'
            print >> logfile, '###Compute BLEU at Iter '+str(iter)



            output_iter = outputfile + str(iter)

            val_start_time = time.time()

            print >>logfile, "Decoding took {} minutes".format(float(time.time() - val_start_time) / 60.)

            translate_file(options,
                           model_file_name,
                           worddicts[0],
                           worddicts_r[1],
                           valid_datasets[0],
                           output_iter)


            cmd_bleu_cmd = ['perl', bleu_scrip, \
                            valid_datasets[2], \
                            '<', \
                            output_iter, \
                            '>'
                            './output.eva']

            subprocess.check_call(" ".join(cmd_bleu_cmd), shell=True)

            fin = open('./output.eva', 'rU')
            out = re.search('BLEU = [-.0-9]+', fin.readlines()[0])
            fin.close()

            bleu_score = float(out.group()[13:])

            print >>logfile, 'Iter '+str(iter) + 'BLEU: ' + str(bleu_score)

            if bleu_score > best_bleu:
                best_bleu = bleu_score
                best_bleu_iter = iter

            print >>logfile, '## Best BLEU: ' + str(best_bleu) + 'at Iter' + str(best_bleu_iter)

            logfile.flush()

        logfile.close()



if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('model', type=str)
    parser.add_argument('pklmodel', type=str)
    parser.add_argument('logfile', type=str)
    parser.add_argument('outputfile', type=str)
    parser.add_argument('bleu_scrip', type=str)
    parser.add_argument('dictionary', type=str)
    parser.add_argument('dictionary_target', type=str)
    parser.add_argument('dictionary_chunk', type=str)
    parser.add_argument('valid_source', type=str)
    parser.add_argument('valid_target', type=str)
    parser.add_argument('valid_reference', type=str)

    args = parser.parse_args()

    main(args.model,
         args.pklmodel,
         args.logfile,
         args.outputfile,
         args.bleu_scrip,
         valid_datasets=[args.valid_source, args.valid_target, args.valid_reference],
         dictionaries=[args.dictionary, args.dictionary_target],
         dictionary_chunk=args.dictionary_chunk )

