#!/usr/bin/env python3
import logging
from datetime import datetime, timedelta
from logging.handlers import TimedRotatingFileHandler
import os
import time
import hashlib
import hmac
import base64
import requests
import socket
import datetime
from requests import status_codes
#from delta_rest_client import DeltaRestClient, create_order_format, cancel_order_format, round_by_tick_size, OrderType, TimeInForce
############################new variables###################
master_config   = [[],[0,0.3,0.1,100,'C',""],[0,0.3,0.1,100,'P',""],[0,0.1,0.1,500,'C',""],[0,0.1,0.1,100,'P',""]]
#Level 0: sheet , ce_daily,pe_daily,ce_monthly,pe_monthly: 
#Level 1: Each list from 1-4: status,wait toler,sl toler,spot toler,coin name (P-BTC) ,expiry  

master_context  = [[[],[]], [[-1,-1,-1],[],[],[[0,0],[0,0]]] , [[-1,-1,-1],[],[],[[0,0],[0,0]]] , [[-1,-1,-1],[],[],[[0,0],[0,0]]] , [[-1,-1,-1],[],[],[[0,0],[0,0]]] ]
# Level 0: [spot_price, ce_daily,pe_daily,ce_monthly,pe_monthly..
# Level 1: from 1-4: at 0 :[atm_sym,atm_newval,atm_oldval] at 1: [active orders list:scrip, size*count, ltp] 2: [passive orders list:scrip, size*count, price,stopprice,product_id,id,tag], 3: last stoploss [buy,sell]

master_handle   = []

master_lock     = [0,0,0] # 0 free , 1 in use ...[master_config,master_context,master_handle]

master_log      = ""
max_type        = 2 # only daily ce and pe , 4 if daily ce,pe + monthly ce,pe

CE              = 1
PE              = 2
CEM             = 3
PEM             = 4

SHEET           = 0
COIN            = 0

# orders
ACT             = 1
PAS             = 2

CTX             = 0
ORDER_LIST      = 1


###########################################################

log = 0
