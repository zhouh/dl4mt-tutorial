import numpy
import cPickle as pkl

import sys
import fileinput

from collections import OrderedDict

def main():
    for filename in sys.argv[1:]:
        print 'Processing', filename

        # for analysis

        cl = 0
        wl = 0
        s1 = 0
        s2 = 0
        s3 = 0
        s4 = 0
        t = 0

        with open(filename, 'r') as f:
            for line in f:

                if len(line.strip()) == 0:
                    if cl <= 30 and wl <= 5:
                        s1 += 1
                    if cl <= 20 and wl <= 5:
                        s2 += 1
                    if cl <= 30 and wl < 4:
                        s3 += 1
                    if cl <= 30 and wl < 3:
                        s4 += 1

                    cl = 0
                    wl = 0

                    t += 1

                    continue

                cl += 1 

                tokens = line.strip().split('\t')

                line = tokens[1]
                
                words_in = line.strip().split(' ')

                words_len = len(words_in)

                if words_len > wl:
                    wl = words_len

        print s1, s2, s3, s4, t
        print 'Done'

if __name__ == '__main__':
    main()
