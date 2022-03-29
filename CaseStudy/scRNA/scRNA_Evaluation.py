import pandas as pd
import numpy as np
import os
from tqdm import trange
from tqdm import tqdm as bar

import sklearn
from sklearn.feature_selection import SelectKBest
from sklearn.feature_selection import f_classif, chi2
from sklearn.metrics import f1_score,adjusted_rand_score,accuracy_score
from sklearn.cluster import KMeans
from sklearn.svm import SVC

import MATTE
print("Using MATTE",MATTE.__version__)

data_dir = r'data/PbmcBench'

# 1.read and prepare data

def Normalization(df_exp):
    df = df_exp.T.copy()
    all_mean = df.mean()
    df_sum = df.sum(axis=0)
    df_ret = np.zeros(shape=df.shape)
    for i in trange(df.shape[1]):
            df_ret[:, i] = (df[:, i]/df_sum[i]) * all_mean
    assert not (df_ret!=0).all()
    return df_ret.T

def prepare_data(data,label):
    cells = data.index
    genes = data.columns
    data = np.log10(1+Normalization(data.values))
    label = pd.Series(data=[i.replace(" ",".") for i in label.values],index=cells)
    data = pd.DataFrame(
        data = data,
        index=cells,columns=genes,dtype=np.float16
    )
    return data,label

def save_data(folder_dir, name, data, label):
    result = os.path.join(folder_dir, name)
    data.to_hdf(result, key='data')
    label.to_hdf(result, key='label')

def read_data(folder_dir,re=False):
    for root,folders,files in os.walk(folder_dir):
        pass
    if len(files) ==2:
        print('first read data in the folder:',folder_dir)

        dname,lname = files
        if 'Labels' in dname:
            dname,lname = lname,dname
        datadir = os.path.join(folder_dir,dname)
        labeldir = os.path.join(folder_dir,lname)

        data = pd.read_csv(datadir,index_col=0)
        label = pd.read_csv(labeldir).iloc[:,0]

        save_data(
            folder_dir, 'unprocessed.h5', data, label
        )

        data,label = prepare_data(data,label)
        save_data(folder_dir, 'processed.h5', data, label)
    elif not re:
        data = pd.read_hdf(os.path.join(folder_dir,'processed.h5'),key='data')
        label = pd.read_hdf(os.path.join(folder_dir,'processed.h5'),key='label')

    else:
        print('Cover original data at',folder_dir)
        data = pd.read_hdf(os.path.join(folder_dir,'unprocessed.h5'),key='data')
        label = pd.read_hdf(os.path.join(folder_dir,'unprocessed.h5'),key='label')
        data,label = prepare_data(data,label)
        save_data(folder_dir, 'processed.h5', data, label)
    return data,label


## FIRST TIME TO RUN
## prepare data for one time and save to hdf file.
for root,folders,files in os.walk(data_dir):
    for f in folders:
        read_data(os.path.join(root,f),re=True)
## ----- prepare end -----

# 2.FS select

training_data_dir = 'data/PbmcBench/10Xv2'
data,label = read_data(training_data_dir)

# ONLY FLOWING CELL TYPES ARE IN ALL DATA
# 
#     Cytotoxic T cell
#     CD4+ T cell
#     CD14+ monocyte
#     B cell
#     Megakaryocyte
#     CD16+ monocyte

filtered_cell_types = ['Cytotoxic.T.cell','CD14+.monocyte','CD4+.T.cell','CD16+.monocyte','B.cell','Megakaryocyte']

label = label[label.isin(filtered_cell_types)]
data = data.loc[label.index,:]


# 2.1 f and chi2 select
feasrank = pd.DataFrame(index=data.columns,columns=['f','chi2'])
for i,func in enumerate([f_classif, chi2]):
    print(i)
    selector = SelectKBest(k='all',score_func=func)
    selector.fit(data,label)
    feasrank.loc[data.columns,['f','chi2'][i]] = selector.scores_


# 2.2 MATTE

AP = MATTE.AlignPipe()
AP.funcs = [AP.funcs[0]] + AP.funcs[4:] ## Delete preprocess step.(performed previously)
ME = MATTE.ModuleEmbedder(pipeline=AP)
ME.gene_rank(data.loc[label.index],label)

feasrank['MATTE'] = ME.gene_ranking

# 2.3 M3Drop implemented 
# in run_M3Drop.R
fea_file_map = {'NB':'NBDropsFS_genes.csv','M3':'M3drop_genes.csv',"HV":'BrenneckeHV_genes.csv'}
for fea,file_dir in fea_file_map.items():
        feasrank[fea] = -pd.read_csv(os.path.join(training_data_dir,'Turn3',file_dir),index_col=0)['q.value']
feasrank.to_csv(os.path.join(training_data_dir,'Turn3',f"{'.'.join([i.split('.')[0] for i in filtered_cell_types])}feasrank.csv"))


# 3. Test 

test_results = pd.DataFrame(columns = ['testdata','fea','k','ari','f1','labled','acc'])

Ks = [20,50,80,100,150,200,250,300]

for root,dirs,files in os.walk(data_dir):
    if root == data_dir:
        Test_data_dirs = dirs
BAR = bar(total=2*len(Test_data_dirs))
for test_data_dir in Test_data_dirs:
    BAR.set_description(f'reading data {test_data_dir}')

    testdata,testlabel = read_data(os.path.join(data_dir,test_data_dir))
    testlabel = testlabel[testlabel.isin(filtered_cell_types)]
    testdata = testdata.loc[testlabel.index,:]

    BAR.set_description('Unsupervised')

    for feas_type in feasrank.columns:
        feas_list = feasrank.loc[:,feas_type].sort_values(ascending=False)
        for k in Ks:
            cluster = KMeans(n_clusters = testlabel.nunique())
            feas = feas_list[:k].index
            feas = feas[feas.isin(testdata.columns)]

            X = testdata.loc[:,feas].values
            y = testlabel.values
            pred = cluster.fit_predict(X,y)
            ari = adjusted_rand_score(y,pred)
            test_results.loc[
                f"{feas_type}_{k}_{test_data_dir}",
                ['testdata','fea','k','ari']] = test_data_dir,feas_type,k,ari
    BAR.update(1)

    BAR.set_description('supervised')

    for feas_type in feasrank.columns:
        feas_list = feasrank.loc[:,feas_type].sort_values(ascending=False)
        for k in Ks:
            feas = feas_list[:k].index
            feas = feas[feas.isin(testdata.columns)]

            clf = SVC(kernel='linear',probability=True)
            clf.fit(data.loc[:,feas],label)

            pred = clf.predict_proba(testdata.loc[:,feas])
            preds = pd.Series(
                [clf.classes_[i] for i in np.argmax(pred,axis=1)],
                index=testdata.index,
            )
            pred = preds[pred.max(axis=1)>=0.7]
            f1 = f1_score(testlabel[pred.index],pred,average='macro')
            labeled = len(pred)/len(testlabel)
            acc = accuracy_score(testlabel[pred.index],pred)
            test_results.loc[
                f"{feas_type}_{k}_{test_data_dir}",
                ['testdata','fea','k','f1','labled','acc']] = test_data_dir,feas_type,k,f1,labeled,acc

    BAR.update(1)


test_results.to_csv(os.path.join(training_data_dir,"testresults.csv"))
