"""Create a shareable figure from the saved complete benchmark summary."""
import json
from pathlib import Path
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
root=Path(__file__).resolve().parent/'results/bucket_gpu'
data=json.loads((root/'summary.json').read_text());routes=['qwen','gliner','combo'];labels=['Qwen\nselection','GLiNER\nselection','GLiNER + Qwen\nselection'];s=[data['methods'][r] for r in routes]
colors=['#3979b9','#24866c','#9462a6'];x=np.arange(3)
fig,axes=plt.subplots(1,3,figsize=(13,4.3));fig.patch.set_facecolor('#fafafa')
acc=np.array([v['correct']*100 for v in s]);ci=np.array([v['accuracy95'] for v in s])
axes[0].bar(x,acc,color=colors,width=.58,yerr=[acc-ci[:,0],ci[:,1]-acc],capsize=4)
axes[0].set(title='Shared Qwen reader accuracy',ylabel='Percent correct, 95% CI',ylim=(0,100))
for i,v in enumerate(acc):axes[0].text(i,v+10,f'{v:.1f}%',ha='center',fontsize=10)
lat=[v['retrieval_median'] for v in s];axes[1].bar(x,lat,color=colors,width=.58);axes[1].set(title='Evidence selection latency',ylabel='Median seconds')
for i,v in enumerate(lat):axes[1].text(i,v+.08,f'{v:.2f}s',ha='center',fontsize=10)
ret=np.array([v['retrieval_cost']*1000 for v in s]);gen=np.array([v['generation_cost']*1000 for v in s]);axes[2].bar(x,ret,color=colors,width=.58,label='Selection');axes[2].bar(x,gen,bottom=ret,color='#bbc3cc',width=.58,label='Shared Qwen reader');axes[2].set(title='Estimated API cost',ylabel='USD per 1,000 answered queries');axes[2].legend(frameon=False,fontsize=8)
for i,v in enumerate(ret+gen):axes[2].text(i,v+.06,f'${v:.2f}',ha='center',fontsize=10)
for ax in axes:
 ax.set_xticks(x,labels);ax.spines[['top','right']].set_visible(False);ax.grid(axis='y',alpha=.18);ax.set_axisbelow(True)
fig.suptitle('FinanceBench bucket: 150 questions across 84 reports',fontsize=15,y=1.02)
fig.text(.5,-.015,'GLiNER: local RTX 5070 Ti. Qwen: remote HF/DeepInfra. Same candidate pool and Qwen reader; GLM judge.\nAPI cost excludes offline indexing, GPU hardware/electricity and evaluation. Latency measured under concurrent API load.',ha='center',fontsize=9)
fig.tight_layout();fig.savefig(root/'comparison.png',dpi=180,bbox_inches='tight');fig.savefig(root/'comparison.svg',bbox_inches='tight')
