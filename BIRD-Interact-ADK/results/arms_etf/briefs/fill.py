#!/usr/bin/env python3
# fill.py <template> <arm> [KEY=VAL ...] -> prints filled brief
import sys
t=open(sys.argv[1]).read(); a=sys.argv[2]
U={'srv':'SRV','dg':'DG','b2':'B2','b2ao':'B2AO','bare':'BARE','bareao':'BAREAO'}[a]
for kv in sys.argv[3:]:
    k,v=kv.split('=',1); t=t.replace(k,v)
t=t.replace('ARMU',U).replace('MODEL',f'Exchange Traded Funds {U}').replace('ARM',a)
print(t)
