#! /usr/bin/env python

import csv
import itertools
import numpy as np
import time
import sys
import operator
import cPickle as pkl
import io
import array
from datetime import datetime

from data_iterator import fopen
from gru_theano import GRUTheano

SENTENCE_START_TOKEN = "SENTENCE_START"
SENTENCE_END_TOKEN = "SENTENCE_END"
UNKNOWN_TOKEN = "UNKNOWN_TOKEN"

def load_data(filename, dict_name, min_sent_characters=50):

    word_to_index = []
    index_to_word = []

    with open(dict_name, 'rb') as f:
        word_to_index = pkl.load(f)

        index_to_word = dict()
        for kk, vv in word_to_index.iteritems():
            index_to_word[vv] = kk

    # Read the data and append SENTENCE_START and SENTENCE_END tokens
    with open(filename, 'rt') as f:


        reader = fopen(filename, 'r')

        # Split full comments into sentences
        sentences = [x.strip().split() for x in reader]
        # Filter sentences
        sentences = [s for s in sentences if len(s) <= min_sent_characters]
        sentences = [s for s in sentences if "http" not in s]
        # Append SENTENCE_START and SENTENCE_END
        sentences = ["%s %s" % (x, index_to_word[0]) for x in sentences]

    print("Parsed %d sentences." % (len(sentences)))


    # Replace all words not in our vocabulary with the unknown token
    for i, sent in enumerate(sentences):
        sentences[i] = [w if w in word_to_index else index_to_word[1] for w in sent]

    # Create the training data
    X_train = np.asarray([[word_to_index[w] for w in sent[:-1]] for sent in sentences])
    y_train = np.asarray([[word_to_index[w] for w in sent[1:]] for sent in sentences])

    return X_train, y_train, word_to_index, index_to_word


def train_with_sgd(model, X_train, y_train, learning_rate=0.001, nepoch=20, decay=0.9,
    callback_every=10000, callback=None):
    num_examples_seen = 0
    for epoch in range(nepoch):
        # For each training example...
        for i in np.random.permutation(len(y_train)):
            # One SGD step
            model.sgd_step(X_train[i], y_train[i], learning_rate, decay)
            num_examples_seen += 1
            # Optionally do callback
            if (callback and callback_every and num_examples_seen % callback_every == 0):
                callback(model, num_examples_seen)            
    return model

def save_model_parameters_theano(model, outfile):
    np.savez(outfile,
        E=model.E.get_value(),
        U=model.U.get_value(),
        W=model.W.get_value(),
        V=model.V.get_value(),
        b=model.b.get_value(),
        c=model.c.get_value())
    print "Saved model parameters to %s." % outfile

def load_model_parameters_theano(path, modelClass=GRUTheano):
    npzfile = np.load(path)
    E, U, W, V, b, c = npzfile["E"], npzfile["U"], npzfile["W"], npzfile["V"], npzfile["b"], npzfile["c"]
    hidden_dim, word_dim = E.shape[0], E.shape[1]
    print "Building model model from %s with hidden_dim=%d word_dim=%d" % (path, hidden_dim, word_dim)
    sys.stdout.flush()
    model = modelClass(word_dim, hidden_dim=hidden_dim)
    model.E.set_value(E)
    model.U.set_value(U)
    model.W.set_value(W)
    model.V.set_value(V)
    model.b.set_value(b)
    model.c.set_value(c)
    return model 

def gradient_check_theano(model, x, y, h=0.001, error_threshold=0.01):
    # Overwrite the bptt attribute. We need to backpropagate all the way to get the correct gradient
    model.bptt_truncate = 1000
    # Calculate the gradients using backprop
    bptt_gradients = model.bptt(x, y)
    # List of all parameters we want to chec.
    model_parameters = ['E', 'U', 'W', 'b', 'V', 'c']
    # Gradient check for each parameter
    for pidx, pname in enumerate(model_parameters):
        # Get the actual parameter value from the mode, e.g. model.W
        parameter_T = operator.attrgetter(pname)(model)
        parameter = parameter_T.get_value()
        print "Performing gradient check for parameter %s with size %d." % (pname, np.prod(parameter.shape))
        # Iterate over each element of the parameter matrix, e.g. (0,0), (0,1), ...
        it = np.nditer(parameter, flags=['multi_index'], op_flags=['readwrite'])
        while not it.finished:
            ix = it.multi_index
            # Save the original value so we can reset it later
            original_value = parameter[ix]
            # Estimate the gradient using (f(x+h) - f(x-h))/(2*h)
            parameter[ix] = original_value + h
            parameter_T.set_value(parameter)
            gradplus = model.calculate_total_loss([x],[y])
            parameter[ix] = original_value - h
            parameter_T.set_value(parameter)
            gradminus = model.calculate_total_loss([x],[y])
            estimated_gradient = (gradplus - gradminus)/(2*h)
            parameter[ix] = original_value
            parameter_T.set_value(parameter)
            # The gradient for this parameter calculated using backpropagation
            backprop_gradient = bptt_gradients[pidx][ix]
            # calculate The relative error: (|x - y|/(|x| + |y|))
            relative_error = np.abs(backprop_gradient - estimated_gradient)/(np.abs(backprop_gradient) + np.abs(estimated_gradient))
            # If the error is to large fail the gradient check
            if relative_error > error_threshold:
                print "Gradient Check ERROR: parameter=%s ix=%s" % (pname, ix)
                print "+h Loss: %f" % gradplus
                print "-h Loss: %f" % gradminus
                print "Estimated_gradient: %f" % estimated_gradient
                print "Backpropagation gradient: %f" % backprop_gradient
                print "Relative Error: %f" % relative_error
                return 
            it.iternext()
        print "Gradient check for parameter %s passed." % (pname)


def print_sentence(s, index_to_word):
    sentence_str = [index_to_word[x] for x in s[1:-1]]
    print(" ".join(sentence_str))
    sys.stdout.flush()

def generate_sentence(model, index_to_word, word_to_index, min_length=5):
    # We start the sentence with the start token
    new_sentence = []
    # Repeat until we get an end token
    while not new_sentence[-1] == index_to_word[0]:
        next_word_probs = model.predict(new_sentence)[-1]
        samples = np.random.multinomial(1, next_word_probs)
        sampled_word = np.argmax(samples)
        new_sentence.append(sampled_word)
        # Seomtimes we get stuck if the sentence becomes too long, e.g. "........" :(
        # And: We don't want sentences with UNKNOWN_TOKEN's
        if len(new_sentence) > 100 or sampled_word == 1:
            return None
    if len(new_sentence) < min_length:
        return None
    return new_sentence

def generate_sentences(model, n, index_to_word, word_to_index):
    for i in range(n):
        sent = None
        while not sent:
            sent = generate_sentence(model, index_to_word, word_to_index)
        print_sentence(sent, index_to_word)

