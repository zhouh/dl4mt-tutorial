#!/bin/bash
#PBS -l nodes=1:ppn=24
#PBS -l walltime=24:00:00
#PBS -N session2/models/memory-set_default
#PBS -A course
#PBS -q ShortQ

export THEANO_FLAGS=device=cpu,floatX=float32

#cd $PBS_O_WORKDIR
python ./translate.py -n -p 8 \
        $HOME/dl4mt-tutorial-master/session2/models/memory-set/model_hal.npz  \
	$HOME/dl4mt-tutorial-master/data/zh2en/filter/corpus.ch.pkl \
	$HOME/dl4mt-tutorial-master/data/zh2en/filter/corpus.en.pkl \
	$HOME/dl4mt-tutorial-master/data/zh2en/devntest/MT02/MT02.src\
	./result/MT02.trans.en

python ./translate.py -n -p 8 \
        $HOME/dl4mt-tutorial-master/session2/models/memory-set/model_hal.npz  \
        $HOME/dl4mt-tutorial-master/data/zh2en/filter/corpus.ch.pkl \
        $HOME/dl4mt-tutorial-master/data/zh2en/filter/corpus.en.pkl \
        $HOME/dl4mt-tutorial-master/data/zh2en/devntest/MT03/MT03.src\
        ./result/MT03.trans.en

python ./translate.py -n -p 8 \
        $HOME/dl4mt-tutorial-master/session2/models/memory-set/model_hal.npz  \
        $HOME/dl4mt-tutorial-master/data/zh2en/filter/corpus.ch.pkl \
        $HOME/dl4mt-tutorial-master/data/zh2en/filter/corpus.en.pkl \
        $HOME/dl4mt-tutorial-master/data/zh2en/devntest/MT04/MT04.src\
        ./result/MT04.trans.en

python ./translate.py -n -p 8 \
        $HOME/dl4mt-tutorial-master/session2/models/memory-set/model_hal.npz  \
        $HOME/dl4mt-tutorial-master/data/zh2en/filter/corpus.ch.pkl \
        $HOME/dl4mt-tutorial-master/data/zh2en/filter/corpus.en.pkl \
        $HOME/dl4mt-tutorial-master/data/zh2en/devntest/MT05/MT05.src\
        ./result/MT05.trans.en

python ./translate.py -n -p 8 \
        $HOME/dl4mt-tutorial-master/session2/models/memory-set/model_hal.npz  \
        $HOME/dl4mt-tutorial-master/data/zh2en/filter/corpus.ch.pkl \
        $HOME/dl4mt-tutorial-master/data/zh2en/filter/corpus.en.pkl \
        $HOME/dl4mt-tutorial-master/data/zh2en/devntest/MT06/MT06.src\
        ./result/MT06.trans.en
