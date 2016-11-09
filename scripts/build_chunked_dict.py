import numpy
import cPickle as pkl

import sys
import fileinput

from collections import OrderedDict

def main():
    for filename in sys.argv[1:]:
        print 'Processing', filename
        word_freqs = OrderedDict()
        chunk_tag_dict = OrderedDict()

        # for analysis
        c5 = 0.0
        c10 = 0.0
        c15 = 0.0
        c20 = 0.0
        c25 = 0.0
        c30 = 0.0
        c35 = 0.0
        c40 = 0.0
        c45 = 0.0
        c50 = 0.0

        w5 = 0.0
        w10 = 0.0
        w15 = 0.0
        w20 = 0.0

        sentence_size = 0.0
        chunk_size = 0.0

        chunk_len = 0.0
        words_len = 0.0

        with open(filename, 'r') as f:
            for line in f:

                if len(line.strip()) == 0:
                    sentence_size += 1

                    if chunk_len <= 5:
                        c5 += 1
                    elif chunk_len <= 10:
                        c10 += 1
                    elif chunk_len <= 15:
                        c15 += 1
                    elif chunk_len <= 20:
                        c20 += 1
                    elif chunk_len <= 25:
                        c25 += 1
                    elif chunk_len <= 30:
                        c30 += 1
                    elif chunk_len <= 35:
                        c35 += 1
                    elif chunk_len <= 40:
                        c40 += 1
                    elif chunk_len <= 45:
                        c45 += 1
                    elif chunk_len <= 50:
                        c50 += 1

                    chunk_len = 0
                    
                    continue

                chunk_len += 1
                chunk_size += 1

                tokens = line.strip().split('\t')

                tag = tokens[0]
                line = tokens[1]
                
                if tag not in chunk_tag_dict:
                    chunk_tag_dict[tag] = 0
                chunk_tag_dict[tag] += 1

                words_in = line.strip().split(' ')

                words_len = len(words_in)

                if words_len <= 3:
                    w5 += 1
                elif words_len <= 4:
                    w10 += 1
                elif words_len <= 5:
                    w15 += 1
                elif words_len <= 6:
                    w20 += 1

                for w in words_in:
                    if w not in word_freqs:
                        word_freqs[w] = 0
                    word_freqs[w] += 1

        words = word_freqs.keys()
        freqs = word_freqs.values()

        sorted_idx = numpy.argsort(freqs)
        sorted_words = [words[ii] for ii in sorted_idx[::-1]]

        worddict = OrderedDict()
        worddict['eos'] = 0
        worddict['UNK'] = 1
        for ii, ww in enumerate(sorted_words):
            worddict[ww] = ii+2

        newChunkDict = OrderedDict()
        newChunkDict['eos'] = 0
        for ii, ww in enumerate(chunk_tag_dict):
            newChunkDict[ww] = ii + 1

        with open('%s.pkl'%filename, 'wb') as f:
            pkl.dump(worddict, f)

        with open('%s.chunktag.pkl'%filename, 'wb') as f:
            pkl.dump(newChunkDict, f)

        print 'word < 3: %f\n <4: %f\n < 5 %f\n <6 %f\n' %(w5/chunk_size, w10/chunk_size, w15/chunk_size, w20/chunk_size)
        print 'chunk < 5: %f\n <10: %f\n < 15 %f\n <20 %f\n < 25: %f\n <30: %f\n < 35 %f\n <40 %f\n < 45 %f\n < 50%f\n' %(c5/sentence_size, c10/sentence_size, c15/sentence_size, c20/sentence_size,c25/sentence_size, c30/sentence_size, c35/sentence_size, c40/sentence_size, c45/sentence_size, c50/sentence_size)

        print 'Done'

if __name__ == '__main__':
    main()
