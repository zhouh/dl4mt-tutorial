import numpy
import cPickle as pkl

import sys
import fileinput

from collections import OrderedDict

def main():

    sf = open(sys.argv[1])
    tf = open(sys.argv[2])
    tchunk = open(sys.argv[3])

    sfo = open(sys.argv[1]+'.filter', 'w')
    tfo = open(sys.argv[2]+'.filter', 'w')

    cl = 0
    wl = 0

    first_line = True

    sline = sf.readline()
    tline = tf.readline()
    line = tchunk.readline()

    while True:

        if len(line.strip()) == 0:


            if cl <= 30 and wl <= 5:
                
                if not first_line:
                    print >> sfo, '\n',
                    print >> tfo, '\n',
                else:
                    first_line = False

                print >> sfo, sline.strip(),
                print >> tfo, tline.strip(),
 
            sline = sf.readline()
            tline = tf.readline()

            line = tchunk.readline()
            if line == '':
                break

            cl = 0
            wl = 0

            continue

        cl += 1 

        tokens = line.strip().split('\t')

        line = tokens[1]
        
        words_in = line.strip().split(' ')

        words_len = len(words_in)


        if words_len > wl:
            wl = words_len

        line = tchunk.readline()
        if line == '':
            break

if __name__ == '__main__':
    main()
