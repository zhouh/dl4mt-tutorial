import numpy
import cPickle as pkl

import sys
import fileinput

from collections import OrderedDict

def main():

    sf = open(sys.argv[1])
    tf = open(sys.argv[2])
    tchunk = open(sys.argv[3])

    sfo = open(sys.argv[4]+'ch.filter', 'w')
    tfo = open(sys.argv[4]+'en.filter', 'w')
    chunk_f = open(sys.argv[4]+'.filter', 'w')

    cl = 0
    wl = 0

    first_line = True

    chunk_instance = []

    count = 0

    while True:

        line = tchunk.readline()
        if line == '':
            break

        if len(line.strip()) == 0:

            sline = sf.readline()
            tline = tf.readline()


            if cl <= 30 and wl <= 5:
                
                print >> sfo, sline.strip()
                print >> tfo, tline.strip()

#                print >> sfo, sline.strip(),
#                print >> tfo, tline.strip(),
                print >> chunk_f, '\n'.join(chunk_instance)
                print >> chunk_f
                count += 1
 
     #       sline = sf.readline()
     #       tline = tf.readline()

            chunk_instance = []
            cl = 0
            wl = 0

            continue


        chunk_instance.append(line.strip())

        cl += 1 

        tokens = line.strip().split('\t')

        line = tokens[1]
        
        words_in = line.strip().split(' ')

        words_len = len(words_in)


        if words_len > wl:
            wl = words_len

    print count
if __name__ == '__main__':
    main()
