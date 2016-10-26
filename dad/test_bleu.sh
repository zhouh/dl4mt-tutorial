#!/bin/bash
#PBS -l nodes=1:ppn=24
#PBS -l walltime=24:00:00
#PBS -N session2_default
#PBS -A course
#PBS -q ShortQ

#export THEANO_FLAGS=device=cpu,floatX=float32

#cd $PBS_O_WORKDIR

for i in 2 3 4 5 6
do 
	./multi-bleu.perl ~/Data/nmt/devntest/MT0${i}/reference < ../result/MT0${i}.trans.en>>results.log
done
