#!/bin/bash
#PBS -l nodes=1:ppn=24
#PBS -l walltime=24:00:00
#PBS -N session2_default
#PBS -A course
#PBS -q ShortQ

#export THEANO_FLAGS=device=cpu,floatX=float32

#cd $PBS_O_WORKDIR

	./multi-bleu.perl ~/workspace/python/nmtdata/devntest/MT02/reference < ./outputs/1.txt
