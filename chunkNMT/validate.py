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


def getBLEU():

    return 0






def main(model,
         pklmodel,
         logfile,
         outputfile,
         bleu_scrip,
         valid_datasets=['../data/dev/newstest2011.en.tok',
                          '../data/dev/newstest2011.fr.tok',
                         '../data/dev/newstest2011.fr.tok'],
         dictionaries=[
              '/data/lisatmp3/chokyun/europarl/europarl-v7.fr-en.en.tok.pkl',
              '/data/lisatmp3/chokyun/europarl/europarl-v7.fr-en.fr.tok.pkl',],
         dictionary_chunk='/data/lisatmp3/chokyun/europarl/europarl-v7.fr-en.en.tok.pkl',
         beginModelIter=200000,
         k_best_keep=10):




    logfile = open(logfile, 'w')

    best_bleu = -1
    best_bleu_iter = beginModelIter

    heap = []
    heapq.heapify(heap)

    for iter in range(beginModelIter, 500000, 1000):

        print iter


        model_file_name = model + '.iter' + str(iter) + '.npz'


        cmd_get_cost = ['python',
                        'computeCost.py',
                        model_file_name,
                        pklmodel,
                        dictionaries[0],
                        dictionaries[1],
                        dictionary_chunk,
                        valid_datasets[0],
                        valid_datasets[1],
                        './cost.result']

        subprocess.check_call(" ".join(cmd_get_cost), shell=True)

        fin = open('./output.eva', 'rU')
        out = fin.readline()

        currentIterCost = float(out.strip()) * -1
        fin.close()


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

            cmd_translate = ['python',
                            'translate_gpu.py',
                            model_file_name,
                            pklmodel,
                            dictionaries[0],
                            dictionaries[1],
                            valid_datasets[0],
                            './output.eva']

            subprocess.check_call(" ".join(cmd_translate), shell=True)


            print >>logfile, "Decoding took {} minutes".format(float(time.time() - val_start_time) / 60.)



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

            bleu_score = float(out.group()[7:])

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

