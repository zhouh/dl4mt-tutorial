#!/bin/bash
#PBS -l nodes=1:ppn=24
#PBS -l walltime=24:00:00
#PBS -N session2_default
#PBS -A course
#PBS -q ShortQ

export THEANO_FLAGS=device=cpu,floatX=float32

#cd $PBS_O_WORKDIR

for((i=500000;i<504000;i=i+1000));
do python ./translate.py -n -p 6 \
        $HOME/dl4mt-tutorial-master/session2/model_hal.iter${i}.npz  \
	$HOME/dl4mt-tutorial-master/data/zh2en/filter/corpus.ch.pkl \
	$HOME/dl4mt-tutorial-master/data/zh2en/filter/corpus.en.pkl \
	$HOME/dl4mt-tutorial-master/data/zh2en/devntest/MT02/MT02.src\
	./output/MT02.trans${i}.en;
done

