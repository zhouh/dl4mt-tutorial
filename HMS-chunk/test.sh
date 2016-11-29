#!/bin/bash
#PBS -l nodes=1:ppn=24
#PBS -l walltime=24:00:00
#PBS -N session2_default
#PBS -A course
#PBS -q ShortQ

export THEANO_FLAGS=device=cpu,floatX=float32

#cd $PBS_O_WORKDIR
python ./translate.py -n -p 4 \
	./model_hal.npz  \
	/home/Data/nmt/corpus.ch.pkl \
	/home/Data/nmt/corpus.en.pkl \
	/home/Data/nmt/devntest/MT02/MT02.src \
	./test.result



