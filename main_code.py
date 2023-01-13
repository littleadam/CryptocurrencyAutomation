#!/usr/bin/env python3
#corrections
#============
# if an SL order for buy is hit ,place the next buy trigger at last sl or last max premium and dont set 20% change
# format active  [[['C-BTC-29400-110622', -1, '65.0000000', 60541, 65.09934238, '65']], 
# format passive [['C-BTC-29400-110622', 1, '91.1', '91.1', 60543, 830119691]
import os
import hashlib
import hmac
import base64
import requests
import time
from datetime import datetime, timedelta
import threading
import googlesheet
import logging
from logging.handlers import TimedRotatingFileHandler
import gettimer
from  gettimer import next_expiry
import pdb
#try:
#    from googlesheet import coin_type
#except:
#    from .googlesheet import coin_type
from deltaapi import*
from gettimer import next_expiry
#from header import *
#from google.auth.exceptions import TransportError
from socket import gethostbyname, gaierror

from delta_rest_client import DeltaRestClient
from header import master_config,master_context,master_handle,master_lock,max_type

# cancel not seen , sl order keeps increasing(should be a common problem)
# while adding ,add to existing order , not a new one at ATM

delta           = ''
deltaorder      = ''
order           = ''
context         = ''
total_orders    = ''
###########################################################
CE		= 1
PE		= 2
CEM		= 3
PEM		= 4

SHEET		= 0
COIN		= 0

# orders
ACT		= 1
PAS		= 2

#CTX		= 0
ORDER_LIST	= 1

breakeven       = 100
seperator       = '-'

EXPIRY          = 5
LIVE            = 0
LOT             = 8
LAST_SL         = 3
VALUE           = 1
BUY             = 0
SELL            = 1
SCRIP           = 0

TOL             = 1
SL_TOL          = 2
SPOT_TOL        = 3
SPOT_LTP        = 0

MIN_SELL_PRE    = 30.0
MIN_BUY_PRE     = 20 #150.0
buy_enabled     = 1 # allow buy
sell_enabled    = 0 # allow sell
ORDER_ENT       = 5 # entry price 
SELL_CLOSE_VAL  = 30.0 # Target price for sell orders

order_status_change = 0
###########################################################

delete_context  = []

gains           = 0
temp = 0
trade_context   = [0,0,0,0,0,0,0,0,0,0]  # [spot price,ce_scrip,pe_scrip,ce_val,pe_val,funds]
log             = ""             # log handler
beep            = lambda x: os.system("echo -n '\a';sleep 0.2;" * x)
ORDER_SCRIP =0
ORDER_LOT   =1
ORDER_LTP   =2
ORDER_TRIG  =3
ORDER_PID   =4
ORDER_ID    =5

class utilities:
    def __init__(self):
        print("")

    def create_log_file(self):
        global log

        logger = logging.getLogger('90dollars')
        logger.setLevel(logging.DEBUG)
        formatter = logging.Formatter(fmt='%(asctime)s %(name)-12s %(levelname)-8s -%(message)s',
                                  datefmt='%m-%d-%y %H:%M:%S')
        fh = TimedRotatingFileHandler('90dollars.log', when='W0')
        fh.setFormatter(formatter)
        logger.addHandler(fh)
        log = logger
        return(logger)
    
    def closest_order (self,scrip,factor,TYPE):
        global seperator
        global delta
        out = [-1,-1]
        ref_itm = scrip

        for i in range(0,5):
            ctx         = ref_itm.split(seperator)
            ctx[2]      = str(int(ctx[2]) +pow(-1,TYPE)*factor) # go 'factor' points down
            ref_itm     = seperator.join(ctx)
            val_itm     = delta.get_current_value(ref_itm)
            if(val_itm  != -1):
                pid  = delta.get_product_id(ref_itm)
                if(pid != -1):
                    out[0]  = ref_itm
                    out[1]  = pid
                break
        return(out)

        

    def get_closest_strike(self,ctx_type,spot_price,diff):
        global master_config
        global delta
        out = [-1,"",0]
        COIN            = 4
        EXPIRY          = 5

        factor  = -1
        add     = 1
        TYPE    = ctx_type
        
        if(TYPE%2 == 1):
            spot = spot_price + diff
        else:
            spot = spot_price - diff
        #print(f"Spot price is {spot} {spot_price}")
        ref1 = abs(spot - int(spot/50)*50)
        ref2 = abs(spot - (int(spot/50)+1)*50)
        if(ref1<ref2):
            base_value = (int(spot/50))*50
            factor      = 1
        else:
            base_value = (int(spot/50)+1)*50
            factor = -1
        
        strike = base_value
        scrip   = master_config[TYPE][COIN]+"-"+str(strike)+"-"+master_config[TYPE][EXPIRY]
        val     = delta.get_current_value(scrip)
        if(val != -1):
            out[0] = 0
            out[1] = scrip
            out[2] = val
            return(out)
        
        for i in range(1,10):
            strike  = strike + factor*i*50
            scrip   = master_config[TYPE][COIN]+"-"+str(strike)+"-"+master_config[TYPE][EXPIRY]
            val     = delta.get_current_value(scrip)
            if(val != -1):
                out[0] = 0
                out[1] = scrip
                out[2] = val
                return(out)

            factor = factor* -1
        return(out)

    def check_expiry(self,TYPE):
        global master_context
        global master_config
        global ACT
        global PAS
        global deltaorder
        global seperator
        #if(master_context[TYPE][ACT] != [] or master_context[TYPE][ACT] !=0 or master_context[TYPE][ACT] != None):
        #    return(0)
        
        out = util.check_premium_expiry(TYPE)
        if(out == -1):# cancel all pending orders and change the expiry dates
            master_config[TYPE][EXPIRY]  =  gettimer.second_next_expiry()
            for order in master_context[TYPE][PAS]:
                exp = order[ORDER_SCRIP].split(seperator)[3]
                if(exp not in master_config[TYPE][EXPIRY]):
                    response = -1
                    response  = deltaorder.cancel(order[ORDER_PID],order[ORDER_ID])
                    if(response != -1):
                        response = 0

    def place_suitable_order (self,TYPE,gap,buysell,ref_order):
        global master_config
        global master_context
        global LIVE
        global SCRIP
        global delta
        global LOT
        global SHEET
        global deltaorder
        global util
        global ORDER_PID
        global ORDER_LTP
        global ORDER_SCRIP

        factor = 0
        if(ref_order == 0):
            scrip       = master_context[TYPE][LIVE][SCRIP]
            val         = delta.get_current_value(scrip)
            if(val == -1):
                print(f"Could not fetch ATM for {scrip}")
                return(val)
        

            ctx         = scrip.split(seperator)
            ctx[2]      = str(int(ctx[2]) +pow(-1,TYPE)*gap) # go 'gap' points down
            ref_itm     = seperator.join(ctx)
            val_itm     = delta.get_current_value(ref_itm)
            if(val_itm  == -1):
                print(f"Could not fetch value for {ref_itm}")
                return(val_itm)
            if(float(val_itm) < 10): # value is less than 10..dont place such orders as the are likel to go into losses
                return(-1)
            factor = (float(val_itm)/float(val))-1

            ctx         = scrip.split(seperator)
            ctx[2]      = str(int(ctx[2]) -pow(-1,TYPE)*gap) # go 'gap' points up
            out         = util.get_closest_strike(TYPE,float(ctx[2]),0)
            if(out[0] == -1):
                print(f"Could not get closest strike for {ctx[2]}")
                return(-1)
            ref_otm     = out[1]
            val_otm     = float(out[2])
            if(val_otm  == -1):
                print(f"Could not fetch value for {ref_otm}")
                return(val_otm)
            if(float(val_otm) < 10): # value is less than 10..dont place such orders as the are likel to go into losses
                return(-1)
            #print(ref_otm)
        
            #print(val_otm)
            pid         = delta.get_product_id(ref_otm)

        if(ref_order != 0):
            ref_otm = ref_order[ORDER_SCRIP]
            pid     = ref_order[ORDER_PID]
            val_otm = ref_order[ORDER_LTP] 

        factor      = 0.5
        if(ref_order == 0 or 'buy' in buysell):
            order_val   = float(1+factor)*float(val_otm)
            response    = deltaorder.stoploss_limit(pid,int(master_config[SHEET][LOT]),buysell,order_val+50,order_val,float(val_otm))
        else:
            order_val   = float(1-factor)*float(val_otm)
            response    = deltaorder.stoploss_limit(pid,int(master_config[SHEET][LOT]),buysell,order_val-50,order_val,float(val_otm))
        #response    = deltaorder.stoploss_limit(pid,int(master_config[SHEET][LOT]),'buy',(val_otm+150),(val_otm+100),float(val_otm))
        if(response == -1):
            print(f"{buysell} order for {ref_otm} failed")
        else:
            print(f"{buysell} order for {ref_otm} at {order_val}({factor*100}% Trigger), Placed")
            accounts.parse_passive_orders(response,TYPE)

        return(response)

    def check_premium_expiry(self,ctx_type):
        global master_context
        global master_config
        global ACT
        global PAS

        COIN            = 4
        EXPIRY          = 5

        global MIN_SELL_PRE 
        GAP             = 250
        TYPE            = ctx_type
        LIVE            = 0
        SCRIP           = 0

        if(TYPE%2 ==1):
            factor = 1
        elif(TYPE%2 == 0):
            factor = -1
        
        scrip = master_context[TYPE][LIVE][SCRIP]   
        value = float(scrip.split('-')[2]) + (factor)*GAP # 300 points away from ATM
        for i in range(0,5): # 500 points OTM
            multiplier = i *50
            
            if(multiplier != 0):
                strike = str((int(value/multiplier) + int(factor))*multiplier) # go towards OTM
            else:
                strike = str(value)
            scrip    = master_config[TYPE][COIN]+"-"+strike+"-"+master_config[TYPE][EXPIRY]
            val      = delta.get_current_value(scrip)
            if(float(val)> MIN_SELL_PRE):
                return(0)

        if(master_context[TYPE][ACT] != [] or master_context[TYPE][ACT] !=0 or master_context[TYPE][ACT] != None):
            return(0)

        return(-1)

    def check_order(self,order_type,ctx_type): # order_type: 0:buy 1 sell ,
        global master_context
        global ACT
        global PAS
        global ORDER_LOT

        SCRIP = 0
        VALUE = 1
        LAST_SL = 3

        TYPE = ctx_type
        response = 0
        for a_order in master_context[TYPE][ACT] :
            if(a_order[ORDER_LOT] > 0 and order_type == 0): # buy order match
                response = 1
                master_context[TYPE][LAST_SL][order_type][SCRIP] = a_order[SCRIP] 
                break
            if(a_order[ORDER_LOT] < 0 and order_type == 1): # sell order match
                response = 1
                master_context[TYPE][LAST_SL][order_type][SCRIP] = a_order[SCRIP] 
                break
        # for p orders too ,set last _sl liek above but ignore hedge orders    
        for p_order in master_context[TYPE][PAS] :
            if(int(p_order[ORDER_LOT]) > 0 and order_type == 0): # buy order match
                response = 2
                break
            if(int(p_order[ORDER_LOT]) < 0 and order_type == 1): # sell order match
                for a_order in master_context[TYPE][ACT] :# ignore hedge orders
                    if(p_order[SCRIP] in a_order[SCRIP]):
                        continue
                    else:
                        master_context[TYPE][LAST_SL][order_type][SCRIP] = p_order[SCRIP]
                        response = 2
                        break
        if(response == 0):
            return(-1)

    def limit_order_create (self,buysell,scrip,ctx_type,factor,tot_orders,tolerance):
        global master_config
        global master_context
        global ACT
        global PAS
        global accounts
        global delta
        global seperator
        global MIN_SELL_PRE
        global MIN_BUY_PRE
        global delete_context
        global util

        print(f"\nlimit_order_create {buysell} Context is {delete_context}")
        local_log   = ""
        out         = [0,""]
        STATUS      = 0
        COIN        = 4
        EXPIRY      = 5

        PREMIUM_DIFF= 50.0
        TYPE        = ctx_type
        LAST_SL     = 3
        LIVE        = 0
        SCRIP       = 0
        VALUE       = 1
        SHEET       = 0
        SPOT_LTP    = 0
        BUY         = 0
        
        #val         = -1	
        #val         = float(delta.get_current_value(scrip))            # ATM val
        
        if(factor != 2):
            last_scr    =   master_context[TYPE][LAST_SL][BUY][SCRIP]
            last_value  =   master_context[TYPE][LAST_SL][BUY][VALUE]
            #if(('buy' in buysell)  and (scrip in last_scr) and (float(val) < last_value)):
            #    print(f"buy order not placed.ltp:{val} for scrip {scrip} is less than last ltp{last_value}.")
            #    return(0)
        
        val = -1
        out = util.get_closest_strike(TYPE,float(scrip.split(seperator)[2]),0)
        if(out[0] != -1):
            scrip   = out[1]
            val     = out[2]
        
        if(val == -1):
            print(f"Error fetching the proper strike for {scrip}")
            return(-1)

        #print(f"atm is {val}")
        #if(val == -1 or val == 0):
        #    for i in range(1,10):
        #        multiplier = i *50
        #        #print(scrip)
        #        value   = float(scrip.split('-')[2])
        #        strike  = str((int(value/multiplier)+int(factor))*multiplier)
        #        scrip   = master_config[TYPE][COIN]+"-"+str(strike)+"-"+master_config[TYPE][EXPIRY]
        #        val     = delta.get_current_value(scrip)
        #        if(val != -1 and val != 0): 
        #            val = float(val)
        #            break


        if(float(val)<MIN_BUY_PRE and ('buy' in buysell) and factor !=2):
            #local_log = local_log + " " +f"ATM value({val}) of {scrip} is less than 150 .so, not placing any Buy order."
            out[0] = -1
            out[1] = local_log
            print(f"ATM {val} less than {MIN_BUY_PRE} for buy order {scrip}.")
            return(out)
        if(float(val)<MIN_SELL_PRE and ('sell' in buysell)): # this is for premium of 0.03 US$.dont go below this 
            #local_log = local_log + " " +f"ATM value({val}) of {scrip} is less than 30 .so, not placing any sell  order."
            
            if(factor != -2):  # only for non-hedge orders 
                ctx         = scrip.split(seperator)
                ctx[2]      = str(int(ctx[2]) - 100) # go 100 points up and then come down
                ref_scrip   = seperator.join(ctx)

                for diff in range(0,300,50):
                    ctx         = ref_scrip.split(seperator)
                    ctx[2]      = str(int(ctx[2]) + diff)
                    ref_scrip   = seperator.join(ctx)
                    scrip       = ref_scrip
                    val         = delta.get_current_value(ref_scrip)
                    ctx[2]      = str(int(ctx[2]) - diff) # revert back for next iteration
                    ref_scrip   = seperator.join(ctx)

                    if(float(val) > MIN_SELL_PRE):
                        break
            
            if(float(val)< MIN_SELL_PRE and val != -1 and factor != -2):
                out[0] = -1
                out[1] = local_log
                print(f"ATM {val} less than 150 for sell order {scrip}")
                return(out)
        else:
            #print(f"value is {val} scrip is {scrip}")
            val = float(val)
                    
        #val         = float(delta.get_current_value(scrip))
        pid         = delta.get_product_id(scrip)
        new_factor  = factor*master_config[TYPE][tolerance]
        if('sell' in buysell): # keep half tolerance for sell orders.for hedge ,call with 2x so that this gives x 
            new_factor = float(new_factor)/2
            #if(factor == -2):
            #    new_factor = -1*new_factor

        BUY         = 0
        SELL        = 1
        
        response = -1
        limit = (1+new_factor)*float(val)
        #print(f"new factor {new_factor} val {val} lim {limit} factor {factor}")
        sl = (1+2*new_factor)*float(val)
        if(abs(factor)<2): # normal order ,factor is -1 or +1
            atm_strike      = 0
            scrip_strike    = 0
            if('buy' in buysell and master_context[TYPE][LAST_SL][BUY][VALUE] != 0): #recreate sl hit old order,this time with 5% tol
                scrip_strike= float(scrip.split('-')[2])
                atm_strike  = float(master_context[TYPE][LIVE][SCRIP].split(seperator)[2])
                if(factor*(atm_strike-scrip_strike) > 0.0 and abs(factor) == 1):
                    new_factor = new_factor/4 # 5% tolerance 
            #print(f"\nLastBuy:{master_context[TYPE][LAST_SL][BUY][VALUE]} atm:{atm_strike} scripstrike {scrip_strike} factor:{factor}")
        
            sl = (1+2*new_factor)*float(val)
            if(sl < 0.5):
                sl = 0.5
            limit = (1+new_factor)*float(val)
            if(limit< 1): # no use in placing such a low limit order .so, just return
                #print(f" limit price{limit} is less than 1 ,so no order is placed")
                limit = 1
                return(out)
        elif('sell' in buysell and abs(factor) == 2 and (val-limit) > PREMIUM_DIFF): # factor is -2.choose closest btwn 50 diff and tol
            limit = float(val) -PREMIUM_DIFF
            sl    = float(val) -(1.5*PREMIUM_DIFF)
            if(sl < 0.5):
                sl = 0.5

        elif('buy' in buysell and abs(factor) == 2 and (limit-val) > PREMIUM_DIFF): # factor is -2.choose closest btwn 50 diff and tol
            limit = float(val) +PREMIUM_DIFF
            sl    = float(val) +(1.5*PREMIUM_DIFF)
            if(sl < 0.5):
                sl = 0.5

        print(f"order: {buysell} {abs(tot_orders)} for {scrip} at sl:{sl} limit:{limit} val:{val}")
        response = -1

        response = deltaorder.stoploss_limit(pid,abs(tot_orders),buysell,sl,limit,float(val))

        if(response == -1):
            print(f"{buysell} order for  {scrip} failed")
            out[0] = response
            return(out)
        else:
            #print(response)
            accounts.parse_passive_orders(response,TYPE)
            print(f"\n\nCreate {buysell} order for type {TYPE}:")
            print(f"scrip : {scrip} BTC-fut: {master_context[SHEET][SPOT_LTP]}: val {val} limit {limit} ")
            print(f"Active:{master_context[TYPE][ACT]}")
            print(f"Passive:{master_context[TYPE][PAS]}")
            out[0] = 1
            local_log = local_log +" "+f"placed stoploss limit {buysell} for {scrip}:{val} with tolerance {new_factor}, sl {sl} and limit {limit}."
            if(factor == -2): # use hedge order data as last SL
                master_context[TYPE][LAST_SL][BUY][SCRIP] = scrip
                master_context[TYPE][LAST_SL][BUY][VALUE] = limit
            elif('buy' in buysell and factor != 2):
                master_context[TYPE][LAST_SL][SELL][SCRIP] = scrip
                master_context[TYPE][LAST_SL][SELL][VALUE] = limit

            #elif('sell' in buysell):
            #    master_context[TYPE][LAST_SL][SELL][SCRIP] = scrip
            #    if(abs(factor) == 2): # hedge order.mark this as SL value for 'BUY' order and not for 'SELL' order 
            #        master_context[TYPE][LAST_SL][BUY][VALUE] = limit

            ######## update passive list temporaily
            #if('buy' in buysell):
            #    size = 1
            #elif('sell' in buysell):
            #    size = -1
            #else:
            #    size = 0

            #item = [scrip,size,pid,sl,limit,pid,0]
            #master_context[TYPE][PAS].append(item)
            ########################################

            master_config[TYPE][STATUS] = 1
            local_log = local_log + " "+f"Last SL {buysell} is set to {scrip} and status for type {TYPE} is set."

            beep(1)
            out[1] = local_log
        return(out)
    # write a truth table and evaluate
    def decider (self,ctx_type,hedge):
        global CE
        global PE
        global ACT
        global PAS
        global master_context
        global master_config
        global ORDER_SCRIP
        global ORDER_LOT
        global ORDER_PID
        global ORDER_ID
        global ORDER_LTP
        global BUY
        global SELL
        global breakeven
        global SELL_CLOSE_VAL
        global VALUE

        local_log = ""
        SPOT_PRICE  = 0
        STATUS      = 0
        TYPE        = ctx_type
        ACTIVE_LTP  = 3
        PASSIVE_LTP = 3
        PID         = 3
        buy         = 0
        sell        = 0
        saved       = 0
        GAP         = 300
        
        hedge_list  = []

        sell_hedged = 0
        sell_hedge_list = []
        
        HEDGE_LTP   = 1
        ORDER_LMT   = 3  
        ORDER_PR    = 2
        val         = 0.0
        out         = [0,0,0]
        
        reponse     = 0
        if(TYPE%2 ==0):
            direction = -1
        elif(TYPE%2 ==1):
            direction = 1
        #print(master_context[TYPE][PAS])
        spot    = float(master_context[SHEET][SPOT_PRICE])
        #if(len(master_context[TYPE][ACT]) + len(master_context[TYPE][PAS])>4):
        #    print("####################################################")
        #    print("Order count beyond limit")
        #    beep(10)
        #    out[0] = 0
        #    out[1] = 0
        #    return(out)

        if(master_context[TYPE][ACT] != []):
            #print(f"Decider : active order:{master_context[TYPE][ACT]}")
            for order in master_context[TYPE][ACT]:
                breach = 0
                val     = float(delta.get_current_value(order[ORDER_SCRIP]))
                order[ACTIVE_LTP] = val
                if(order[ORDER_LOT]>0): # buy order
                    #master_context[TYPE][LAST_SL][BUY][ORDER_SCRIP] = order[ORDER_SCRIP] 
                    buy     = buy + int(order[ORDER_LOT])
                    local_log = local_log +" "+f"374 buy is {buy} sell {sell}"
                    #hedge   = hedge + int(order[ORDER_LOT])
                    
                    # all buy order need hedge sell ,so queue them and compare in passive list
                    item = []
                    item.insert(0,order[ORDER_SCRIP]) # to be compared with the passive list sell order
                    item.append(val)
                    if(hedge == 1):
                        if(hedge_list == []):
                            hedge_list.insert(0,item) # to be compared with the passive list sell order
                        elif(hedge_list != []):
                            hedge_list.append(item)
                        local_log = local_log +" "+f"383 hedged list {hedge_list}"

                elif(order[ORDER_LOT]<0): # sell order
                    sell    = sell + abs(int(order[ORDER_LOT]))
                    local_log = local_log +" "+f"387 sell is {sell} buy {buy} direction {direction}"
                    breach  = direction *(float(order[ORDER_SCRIP].split('-')[2]) + float(order[ORDER_LTP]) - spot)
                    
                    #if(breach > 0 and breach   >= (1.5*breakeven) and breach>GAP): # if strike goes beyond 750 points,move  on the winning leg
                    #    breach  = -1
                    #print(f"active ltp {order[ACTIVE_LTP]} sell close {SELL_CLOSE_VAL}")
                    if(order[ACTIVE_LTP] < SELL_CLOSE_VAL and int(order[ACTIVE_LTP]) != 0): # target (val = 15) hit...close the order
                        print(f"Sell close value hit {order}")  
                        master_context[TYPE][LAST_SL][SELL][ORDER_SCRIP] = 0
                        master_context[TYPE][LAST_SL][SELL][VALUE]       = 0
                        breach = -1 

                    if(breach <0):# and len(master_context[TYPE][ACT]) <2): #Sell order has become ATM and there is no active buy
                        local_log = local_log +"\n "+"ATM hit...bu market order"
                        local_log = local_log +"\n "+f" breach {breach} active count {master_context[TYPE][ACT]} scrip {order[ORDER_SCRIP]} spot {spot}"
                        # This is redundant but can be used for double confimation
                        #order[ORDER_LOT]         = delta.get_product_id(order[ORDER_SCRIP])

                        response = 0
                        
                        if(hedge == 1):
                            # cancel hedge before closing active order
                            cancel_hedge = 0
                            for p_order in master_context[TYPE][PAS]:
                                if((order[ORDER_SCRIP] in p_order[ORDER_SCRIP]) and (abs(order[ORDER_LOT]) == abs(p_order[ORDER_LOT]))):
                                    if(cancel_hedge != 1):
                                        print("line 460")
                                        response  = deltaorder.cancel(p_order[ORDER_PID],p_order[ORDER_ID])
                                        if(response != -1):
                                            master_context[TYPE][PAS] = [x_order for x_order in master_context[TYPE][PAS] if(x_order != p_order)]

                        response = deltaorder.market_order(order[PID],abs(order[ORDER_LOT]),'buy') # close order
                        print("placed order")
                        if(response != -1):
                            print(f"\n\n bu order placed successfull {response}")
                            print(f"\n\nlocal log is : \n{local_log}")
                            res = 0
                            master_context[TYPE][LAST_SL][SELL][VALUE]   = val
                            master_context[TYPE][LAST_SL][SELL][ORDER_SCRIP]   = order[ORDER_SCRIP]
                            master_context[TYPE][ACT] = [a_order for a_order in master_context[TYPE][ACT] if(a_order != order)]
                            #res = master_context[TYPE][ACT].remove(order) # remove cancelled order from the list
                            sell = sell - abs(int(order[ORDER_LOT])) # update total size
                            local_log = local_log +" "+f"397 sell is {sell} buy {buy}"
                            continue
                        else:
                            print(f"closing of breached order: {order} failed")
                    else:
                        sell_found = 1
                    ########################################added on 6/10##########################    
                    # all sell order need hedge buy ,so queue them and compare in passive list
                    val     = float(delta.get_current_value(order[ORDER_SCRIP]))
                    order[ACTIVE_LTP] = val
                    
                    #print(f"order before adding to sell {order}")
                    item = []
                    item.insert(0,order[ORDER_SCRIP]) # to be compared with the passive list buy order
                    item.append(val)
                    item.append(float(order[ORDER_ENT]))
                    if(hedge == 1):
                        if(sell_hedge_list == []):
                            sell_hedge_list.insert(0,item) # to be compared with the passive list buy order
                        elif(sell_hedge_list != []):
                            sell_hedge_list.append(item)
                    ###########################################################################
                    #master_context[TYPE][LAST_SL][SELL][ORDER_SCRIP] = order[ORDER_SCRIP] 
                    local_log = local_log +" "+f"401 sell is {sell} buy {buy}"
        saved = 0
        if(master_context[TYPE][PAS] != []): # Passive orders
            for order in master_context[TYPE][PAS]:
                breach = 0
                if(order[ORDER_LOT]>0): # buy order
                    ##############################################added on 6/10 ##########################
                    sell_hedge_check = 0
                    for hedge_order in sell_hedge_list:
                        local_log = local_log +" "+f"sell hedge order {hedge_order} order {order}"
                        #print(f"sell hedge order {hedge_order} order {order}")
                        if(hedge_order[ORDER_SCRIP] in order[ORDER_SCRIP] and sell_hedge_check == 0): # last check to handle duplicates
                            sell_hedge_check = 1
                            sell_hedged = 1    
                            #out = 0
                            #print(f"buy:is {order[ORDER_LMT]} -{hedge_order[HEDGE_LTP]} > 50 ? {hedge_order} {order}")
                            val_now = float(order[ORDER_LMT])
                            response = 0
                            if((val_now-hedge_order[HEDGE_LTP]>50.0) and val_now>(hedge_order[ORDER_PR]-10)):
                                print("line 513")
                                response  = deltaorder.cancel(order[ORDER_PID],order[ORDER_ID])
                                if(response == -1):
                                    print(f"cancel of breached hedge buy order: {order} failed")
                                else:
                                    print(f"Cancelled hedge order: {order[ORDER_SCRIP]}")
                                    res = 0
                                    master_context[TYPE][PAS] = [p_order for p_order in master_context[TYPE][PAS] if(p_order != order)]
                                    #res = master_context[TYPE][PAS].remove(order) # remove cancelled order from the list
                                    time.sleep(2)
                                    SL_TOL  = 2
                                    factor  = 2
                                    local_log = local_log +" "+"Placing new buy order as hedge"
                                    print("Buy order place")
                                    response = util.order_val = (1+factor)*val_otm


    def duplicate_check_premium_expiry(self,ctx_type):
        global master_context
        global master_config
        global ACT
        global PAS

        COIN            = 4
        EXPIRY          = 5

        global MIN_SELL_PRE 
        GAP             = 250
        TYPE            = ctx_type
        LIVE            = 0
        SCRIP           = 0

        if(TYPE%2 ==1):
            factor = 1
        elif(TYPE%2 == 0):
            factor = -1

        scrip = master_context[TYPE][LIVE][SCRIP]   
        value = float(scrip.split('-')[2]) + (factor)*GAP # 300 points away from ATM
        for i in range(0,5): # 500 points OTM
            multiplier = i *50
            
            if(multiplier != 0):
                strike = str((int(value/multiplier) + int(factor))*multiplier) # go towards OTM
            else:
                strike = str(value)
            scrip    = master_config[TYPE][COIN]+"-"+strike+"-"+master_config[TYPE][EXPIRY]
            val      = delta.get_current_value(scrip)
            if(float(val)> MIN_SELL_PRE):
                return(0)

        if(master_context[TYPE][ACT] != [] or master_context[TYPE][ACT] !=0 or master_context[TYPE][ACT] != None):
            return(0)

        return(-1)

    def check_order(self,order_type,ctx_type): # order_type: 0:buy 1 sell ,
        global master_context
        global ACT
        global PAS
        global ORDER_LOT

        SCRIP = 0
        VALUE = 1
        LAST_SL = 3

        TYPE = ctx_type
        response = 0
        for a_order in master_context[TYPE][ACT] :
            if(a_order[ORDER_LOT] > 0 and order_type == 0): # buy order match
                response = 1
                master_context[TYPE][LAST_SL][order_type][SCRIP] = a_order[SCRIP] 
                break
            if(a_order[ORDER_LOT] < 0 and order_type == 1): # sell order match
                response = 1
                master_context[TYPE][LAST_SL][order_type][SCRIP] = a_order[SCRIP] 
                break
        # for p orders too ,set last _sl liek above but ignore hedge orders    
        for p_order in master_context[TYPE][PAS] :
            if(int(p_order[ORDER_LOT]) > 0 and order_type == 0): # buy order match
                response = 2
                break
            if(int(p_order[ORDER_LOT]) < 0 and order_type == 1): # sell order match
                for a_order in master_context[TYPE][ACT] :# ignore hedge orders
                    if(p_order[SCRIP] in a_order[SCRIP]):
                        continue
                    else:
                        master_context[TYPE][LAST_SL][order_type][SCRIP] = p_order[SCRIP]
                        response = 2
                        break
        if(response == 0):
            return(-1)

    def duplicate_limit_order_create (self,buysell,scrip,ctx_type,factor,tot_orders,tolerance):
        global master_config
        global master_context
        global ACT
        global PAS
        global accounts
        global delta
        global seperator
        global MIN_SELL_PRE
        global MIN_BUY_PRE
        global delete_context
        global util

        print(f"\nlimit_order_create {buysell} Context is {delete_context}")
        local_log   = ""
        out         = [0,""]
        STATUS      = 0
        COIN        = 4
        EXPIRY      = 5

        PREMIUM_DIFF= 50.0
        TYPE        = ctx_type
        LAST_SL     = 3
        LIVE        = 0
        SCRIP       = 0
        VALUE       = 1
        SHEET       = 0
        SPOT_LTP    = 0
        BUY         = 0
        
        #val         = -1	
        #val         = float(delta.get_current_value(scrip))            # ATM val
        
        if(factor != 2):
            last_scr    =   master_context[TYPE][LAST_SL][BUY][SCRIP]
            last_value  =   master_context[TYPE][LAST_SL][BUY][VALUE]
            #if(('buy' in buysell)  and (scrip in last_scr) and (float(val) < last_value)):
            #    print(f"buy order not placed.ltp:{val} for scrip {scrip} is less than last ltp{last_value}.")
            #    return(0)
        
        val = -1
        out = util.get_closest_strike(TYPE,float(scrip.split(seperator)[2]),0)
        if(out[0] != -1):
            scrip   = out[1]
            val     = out[2]
        
        if(val == -1):
            print(f"Error fetching the proper strike for {scrip}")
            return(-1)

        #print(f"atm is {val}")
        #if(val == -1 or val == 0):
        #    for i in range(1,10):
        #        multiplier = i *50
        #        #print(scrip)
        #        value   = float(scrip.split('-')[2])
        #        strike  = str((int(value/multiplier)+int(factor))*multiplier)
        #        scrip   = master_config[TYPE][COIN]+"-"+str(strike)+"-"+master_config[TYPE][EXPIRY]
        #        val     = delta.get_current_value(scrip)
        #        if(val != -1 and val != 0): 
        #            val = float(val)
        #            break


        if(float(val)<MIN_BUY_PRE and ('buy' in buysell) and factor !=2):
            #local_log = local_log + " " +f"ATM value({val}) of {scrip} is less than 150 .so, not placing any Buy order."
            out[0] = -1
            out[1] = local_log
            print(f"ATM {val} less than {MIN_BUY_PRE} for buy order {scrip}.")
            return(out)
        if(float(val)<MIN_SELL_PRE and ('sell' in buysell)): # this is for premium of 0.03 US$.dont go below this 
            #local_log = local_log + " " +f"ATM value({val}) of {scrip} is less than 30 .so, not placing any sell  order."
            
            if(factor != -2):  # only for non-hedge orders 
                ctx         = scrip.split(seperator)
                ctx[2]      = str(int(ctx[2]) - 100) # go 100 points up and then come down
                ref_scrip   = seperator.join(ctx)

                for diff in range(0,300,50):
                    ctx         = ref_scrip.split(seperator)
                    ctx[2]      = str(int(ctx[2]) + diff)
                    ref_scrip   = seperator.join(ctx)
                    scrip       = ref_scrip
                    val         = delta.get_current_value(ref_scrip)
                    ctx[2]      = str(int(ctx[2]) - diff) # revert back for next iteration
                    ref_scrip   = seperator.join(ctx)

                    if(float(val) > MIN_SELL_PRE):
                        break
            
            if(float(val)< MIN_SELL_PRE and val != -1 and factor != -2):
                out[0] = -1
                out[1] = local_log
                print(f"ATM {val} less than 150 for sell order {scrip}")
                return(out)
        else:
            #print(f"value is {val} scrip is {scrip}")
            val = float(val)
                    
        #val         = float(delta.get_current_value(scrip))
        pid         = delta.get_product_id(scrip)
        new_factor  = factor*master_config[TYPE][tolerance]
        if('sell' in buysell): # keep half tolerance for sell orders.for hedge ,call with 2x so that this gives x 
            new_factor = float(new_factor)/2
            #if(factor == -2):
            #    new_factor = -1*new_factor

        BUY         = 0
        SELL        = 1
        
        response = -1
        limit = (1+new_factor)*float(val)
        #print(f"new factor {new_factor} val {val} lim {limit} factor {factor}")
        sl = (1+2*new_factor)*float(val)
        if(abs(factor)<2): # normal order ,factor is -1 or +1
            atm_strike      = 0
            scrip_strike    = 0
            if('buy' in buysell and master_context[TYPE][LAST_SL][BUY][VALUE] != 0): #recreate sl hit old order,this time with 5% tol
                scrip_strike= float(scrip.split('-')[2])
                atm_strike  = float(master_context[TYPE][LIVE][SCRIP].split(seperator)[2])
                if(factor*(atm_strike-scrip_strike) > 0.0 and abs(factor) == 1):
                    new_factor = new_factor/4 # 5% tolerance 
            #print(f"\nLastBuy:{master_context[TYPE][LAST_SL][BUY][VALUE]} atm:{atm_strike} scripstrike {scrip_strike} factor:{factor}")
        
            sl = (1+2*new_factor)*float(val)
            if(sl < 0.5):
                sl = 0.5
            limit = (1+new_factor)*float(val)
            if(limit< 1): # no use in placing such a low limit order .so, just return
                #print(f" limit price{limit} is less than 1 ,so no order is placed")
                limit = 1
                return(out)
        elif('sell' in buysell and abs(factor) == 2 and (val-limit) > PREMIUM_DIFF): # factor is -2.choose closest btwn 50 diff and tol
            limit = float(val) -PREMIUM_DIFF
            sl    = float(val) -(1.5*PREMIUM_DIFF)
            if(sl < 0.5):
                sl = 0.5

        elif('buy' in buysell and abs(factor) == 2 and (limit-val) > PREMIUM_DIFF): # factor is -2.choose closest btwn 50 diff and tol
            limit = float(val) +PREMIUM_DIFF
            sl    = float(val) +(1.5*PREMIUM_DIFF)
            if(sl < 0.5):
                sl = 0.5

        print(f"order: {buysell} {abs(tot_orders)} for {scrip} at sl:{sl} limit:{limit} val:{val}")
        response = -1

        response = deltaorder.stoploss_limit(pid,abs(tot_orders),buysell,sl,limit,float(val))

        if(response == -1):
            print(f"{buysell} order for  {scrip} failed")
            out[0] = response
            return(out)
        else:
            #print(response)
            accounts.parse_passive_orders(response,TYPE)
            print(f"\n\nCreate {buysell} order for type {TYPE}:")
            print(f"scrip : {scrip} BTC-fut: {master_context[SHEET][SPOT_LTP]}: val {val} limit {limit} ")
            print(f"Active:{master_context[TYPE][ACT]}")
            print(f"Passive:{master_context[TYPE][PAS]}")
            out[0] = 1
            local_log = local_log +" "+f"placed stoploss limit {buysell} for {scrip}:{val} with tolerance {new_factor}, sl {sl} and limit {limit}."
            if(factor == -2): # use hedge order data as last SL
                master_context[TYPE][LAST_SL][BUY][SCRIP] = scrip
                master_context[TYPE][LAST_SL][BUY][VALUE] = limit
            elif('buy' in buysell and factor != 2):
                master_context[TYPE][LAST_SL][SELL][SCRIP] = scrip
                master_context[TYPE][LAST_SL][SELL][VALUE] = limit

            #elif('sell' in buysell):
            #    master_context[TYPE][LAST_SL][SELL][SCRIP] = scrip
            #    if(abs(factor) == 2): # hedge order.mark this as SL value for 'BUY' order and not for 'SELL' order 
            #        master_context[TYPE][LAST_SL][BUY][VALUE] = limit

            ######## update passive list temporaily
            #if('buy' in buysell):
            #    size = 1
            #elif('sell' in buysell):
            #    size = -1
            #else:
            #    size = 0

            #item = [scrip,size,pid,sl,limit,pid,0]
            #master_context[TYPE][PAS].append(item)
            ########################################

            master_config[TYPE][STATUS] = 1
            local_log = local_log + " "+f"Last SL {buysell} is set to {scrip} and status for type {TYPE} is set."

            beep(1)
            out[1] = local_log
        return(out)
    # write a truth table and evaluate
    def decider (self,ctx_type,hedge):
        global CE
        global PE
        global ACT
        global PAS
        global master_context
        global master_config
        global ORDER_SCRIP
        global ORDER_LOT
        global ORDER_PID
        global ORDER_ID
        global ORDER_LTP
        global BUY
        global SELL
        global breakeven
        global SELL_CLOSE_VAL
        global VALUE

        local_log = ""
        SPOT_PRICE  = 0
        STATUS      = 0
        TYPE        = ctx_type
        ACTIVE_LTP  = 3
        PASSIVE_LTP = 3
        PID         = 3
        buy         = 0
        sell        = 0
        saved       = 0
        GAP         = 300
        
        hedge_list  = []

        sell_hedged = 0
        sell_hedge_list = []
        
        HEDGE_LTP   = 1
        ORDER_LMT   = 3  
        ORDER_PR    = 2
        val         = 0.0
        out         = [0,0,0]
        
        reponse     = 0
        if(TYPE%2 ==0):
            direction = -1
        elif(TYPE%2 ==1):
            direction = 1
        #print(master_context[TYPE][PAS])
        spot    = float(master_context[SHEET][SPOT_PRICE])
        #if(len(master_context[TYPE][ACT]) + len(master_context[TYPE][PAS])>4):
        #    print("####################################################")
        #    print("Order count beyond limit")
        #    beep(10)
        #    out[0] = 0
        #    out[1] = 0
        #    return(out)

        if(master_context[TYPE][ACT] != []):
            #print(f"Decider : active order:{master_context[TYPE][ACT]}")
            for order in master_context[TYPE][ACT]:
                breach = 0
                val     = float(delta.get_current_value(order[ORDER_SCRIP]))
                order[ACTIVE_LTP] = val
                if(order[ORDER_LOT]>0): # buy order
                    #master_context[TYPE][LAST_SL][BUY][ORDER_SCRIP] = order[ORDER_SCRIP] 
                    buy     = buy + int(order[ORDER_LOT])
                    local_log = local_log +" "+f"374 buy is {buy} sell {sell}"
                    #hedge   = hedge + int(order[ORDER_LOT])
                    
                    # all buy order need hedge sell ,so queue them and compare in passive list
                    item = []
                    item.insert(0,order[ORDER_SCRIP]) # to be compared with the passive list sell order
                    item.append(val)
                    if(hedge == 1):
                        if(hedge_list == []):
                            hedge_list.insert(0,item) # to be compared with the passive list sell order
                        elif(hedge_list != []):
                            hedge_list.append(item)
                        local_log = local_log +" "+f"383 hedged list {hedge_list}"

                elif(order[ORDER_LOT]<0): # sell order
                    sell    = sell + abs(int(order[ORDER_LOT]))
                    local_log = local_log +" "+f"387 sell is {sell} buy {buy} direction {direction}"
                    breach  = direction *(float(order[ORDER_SCRIP].split('-')[2]) + float(order[ORDER_LTP]) - spot)
                    
                    #if(breach > 0 and breach   >= (1.5*breakeven) and breach>GAP): # if strike goes beyond 750 points,move  on the winning leg
                    #    breach  = -1
                    #print(f"active ltp {order[ACTIVE_LTP]} sell close {SELL_CLOSE_VAL}")
                    if(order[ACTIVE_LTP] < SELL_CLOSE_VAL and int(order[ACTIVE_LTP]) != 0): # target (val = 15) hit...close the order
                        print(f"Sell close value hit {order}")  
                        master_context[TYPE][LAST_SL][SELL][ORDER_SCRIP] = 0
                        master_context[TYPE][LAST_SL][SELL][VALUE]       = 0
                        breach = -1 

                    if(breach <0):# and len(master_context[TYPE][ACT]) <2): #Sell order has become ATM and there is no active buy
                        local_log = local_log +"\n "+"ATM hit...bu market order"
                        local_log = local_log +"\n "+f" breach {breach} active count {master_context[TYPE][ACT]} scrip {order[ORDER_SCRIP]} spot {spot}"
                        # This is redundant but can be used for double confimation
                        #order[ORDER_LOT]         = delta.get_product_id(order[ORDER_SCRIP])

                        response = 0
                        
                        if(hedge == 1):
                            # cancel hedge before closing active order
                            cancel_hedge = 0
                            for p_order in master_context[TYPE][PAS]:
                                if((order[ORDER_SCRIP] in p_order[ORDER_SCRIP]) and (abs(order[ORDER_LOT]) == abs(p_order[ORDER_LOT]))):
                                    if(cancel_hedge != 1):
                                        print("line 460")
                                        response  = deltaorder.cancel(p_order[ORDER_PID],p_order[ORDER_ID])
                                        if(response != -1):
                                            master_context[TYPE][PAS] = [x_order for x_order in master_context[TYPE][PAS] if(x_order != p_order)]

                        response = deltaorder.market_order(order[PID],abs(order[ORDER_LOT]),'buy') # close order
                        print("placed order")
                        if(response != -1):
                            print(f"\n\n bu order placed successfull {response}")
                            print(f"\n\nlocal log is : \n{local_log}")
                            res = 0
                            master_context[TYPE][LAST_SL][SELL][VALUE]   = val
                            master_context[TYPE][LAST_SL][SELL][ORDER_SCRIP]   = order[ORDER_SCRIP]
                            master_context[TYPE][ACT] = [a_order for a_order in master_context[TYPE][ACT] if(a_order != order)]
                            #res = master_context[TYPE][ACT].remove(order) # remove cancelled order from the list
                            sell = sell - abs(int(order[ORDER_LOT])) # update total size
                            local_log = local_log +" "+f"397 sell is {sell} buy {buy}"
                            continue
                        else:
                            print(f"closing of breached order: {order} failed")
                    else:
                        sell_found = 1
                    ########################################added on 6/10##########################    
                    # all sell order need hedge buy ,so queue them and compare in passive list
                    val     = float(delta.get_current_value(order[ORDER_SCRIP]))
                    order[ACTIVE_LTP] = val
                    
                    #print(f"order before adding to sell {order}")
                    item = []
                    item.insert(0,order[ORDER_SCRIP]) # to be compared with the passive list buy order
                    item.append(val)
                    item.append(float(order[ORDER_ENT]))
                    if(hedge == 1):
                        if(sell_hedge_list == []):
                            sell_hedge_list.insert(0,item) # to be compared with the passive list buy order
                        elif(sell_hedge_list != []):
                            sell_hedge_list.append(item)
                    ###########################################################################
                    #master_context[TYPE][LAST_SL][SELL][ORDER_SCRIP] = order[ORDER_SCRIP] 
                    local_log = local_log +" "+f"401 sell is {sell} buy {buy}"
        saved = 0
        if(master_context[TYPE][PAS] != []): # Passive orders
            for order in master_context[TYPE][PAS]:
                breach = 0
                if(order[ORDER_LOT]>0): # buy order
                    ##############################################added on 6/10 ##########################
                    sell_hedge_check = 0
                    for hedge_order in sell_hedge_list:
                        local_log = local_log +" "+f"sell hedge order {hedge_order} order {order}"
                        #print(f"sell hedge order {hedge_order} order {order}")
                        if(hedge_order[ORDER_SCRIP] in order[ORDER_SCRIP] and sell_hedge_check == 0): # last check to handle duplicates
                            sell_hedge_check = 1
                            sell_hedged = 1    
                            #out = 0
                            #print(f"buy:is {order[ORDER_LMT]} -{hedge_order[HEDGE_LTP]} > 50 ? {hedge_order} {order}")
                            val_now = float(order[ORDER_LMT])
                            response = 0
                            if((val_now-hedge_order[HEDGE_LTP]>50.0) and val_now>(hedge_order[ORDER_PR]-10)):
                                print("line 513")
                                response  = deltaorder.cancel(order[ORDER_PID],order[ORDER_ID])
                                if(response == -1):
                                    print(f"cancel of breached hedge buy order: {order} failed")
                                else:
                                    print(f"Cancelled hedge order: {order[ORDER_SCRIP]}")
                                    res = 0
                                    master_context[TYPE][PAS] = [p_order for p_order in master_context[TYPE][PAS] if(p_order != order)]
                                    #res = master_context[TYPE][PAS].remove(order) # remove cancelled order from the list
                                    time.sleep(2)
                                    SL_TOL  = 2
                                    factor  = 2
                                    local_log = local_log +" "+"Placing new buy order as hedge"
                                    print("Buy order place")
                                    response = util.rder_val = (1+factor)*val_otm


    def check_premium_expiry(self,ctx_type):
        global master_context
        global master_config
        global ACT
        global PAS
        global seperator

        COIN            = 4
        EXPIRY          = 5

        global MIN_SELL_PRE 
        GAP             = 500
        TYPE            = ctx_type
        LIVE            = 0
        SCRIP           = 0

        if(TYPE%2 ==1):
            factor = 1
        elif(TYPE%2 == 0):
            factor = -1

        scrip = master_context[TYPE][LIVE][SCRIP]
        if(scrip == 0 or scrip == -1):
            print(f"Error:live scrip of {TYPE} is {scrip}")
            return(-1)

        value = float(scrip.split(seperator)[2]) + (factor)*GAP # 300 points away from ATM
        for i in range(0,5): # 500 points OTM
            multiplier = i *50
            
            if(multiplier != 0):
                strike = str((int(value/multiplier) + int(factor))*multiplier) # go towards OTM
            else:
                strike = str(value)
            scrip    = master_config[TYPE][COIN]+"-"+strike+"-"+master_config[TYPE][EXPIRY]
            val      = delta.get_current_value(scrip)
            if(float(val)> MIN_SELL_PRE):
                return(0)
            if(val != -1):
                break

        #if(master_context[TYPE][ACT] != [] or master_context[TYPE][ACT] !=0 or master_context[TYPE][ACT] != None):
        #    return(0)

        return(-1)

    def check_order(self,order_type,ctx_type): # order_type: 0:buy 1 sell ,
        global master_context
        global ACT
        global PAS
        global ORDER_LOT

        SCRIP = 0
        VALUE = 1
        LAST_SL = 3

        TYPE = ctx_type
        response = 0
        for a_order in master_context[TYPE][ACT] :
            if(a_order[ORDER_LOT] > 0 and order_type == 0): # buy order match
                response = 1
                master_context[TYPE][LAST_SL][order_type][SCRIP] = a_order[SCRIP] 
                break
            if(a_order[ORDER_LOT] < 0 and order_type == 1): # sell order match
                response = 1
                master_context[TYPE][LAST_SL][order_type][SCRIP] = a_order[SCRIP] 
                break
        # for p orders too ,set last _sl liek above but ignore hedge orders    
        for p_order in master_context[TYPE][PAS] :
            if(int(p_order[ORDER_LOT]) > 0 and order_type == 0): # buy order match
                response = 2
                break
            if(int(p_order[ORDER_LOT]) < 0 and order_type == 1): # sell order match
                for a_order in master_context[TYPE][ACT] :# ignore hedge orders
                    if(p_order[SCRIP] in a_order[SCRIP]):
                        continue
                    else:
                        master_context[TYPE][LAST_SL][order_type][SCRIP] = p_order[SCRIP]
                        response = 2
                        break
        if(response == 0):
            return(-1)

    def limit_order_create (self,buysell,scrip,ctx_type,factor,tot_orders,tolerance):
        global master_config
        global master_context
        global ACT
        global PAS
        global accounts
        global delta
        global seperator
        global MIN_SELL_PRE
        global MIN_BUY_PRE
        global delete_context
        global util

        print(f"\nlimit_order_create {buysell} Context is {delete_context}")
        local_log   = ""
        out         = [0,""]
        STATUS      = 0
        COIN        = 4
        EXPIRY      = 5

        PREMIUM_DIFF= 50.0
        TYPE        = ctx_type
        LAST_SL     = 3
        LIVE        = 0
        SCRIP       = 0
        VALUE       = 1
        SHEET       = 0
        SPOT_LTP    = 0
        BUY         = 0
        
        #val         = -1	
        #val         = float(delta.get_current_value(scrip))            # ATM val
        
        if(factor != 2):
            last_scr    =   master_context[TYPE][LAST_SL][BUY][SCRIP]
            last_value  =   master_context[TYPE][LAST_SL][BUY][VALUE]
            #if(('buy' in buysell)  and (scrip in last_scr) and (float(val) < last_value)):
            #    print(f"buy order not placed.ltp:{val} for scrip {scrip} is less than last ltp{last_value}.")
            #    return(0)
        
        val = -1
        out = util.get_closest_strike(TYPE,float(scrip.split(seperator)[2]),0)
        if(out[0] != -1):
            scrip   = out[1]
            val     = out[2]
        
        if(val == -1):
            print(f"Error fetching the proper strike for {scrip}")
            return(-1)

        #print(f"atm is {val}")
        #if(val == -1 or val == 0):
        #    for i in range(1,10):
        #        multiplier = i *50
        #        #print(scrip)
        #        value   = float(scrip.split('-')[2])
        #        strike  = str((int(value/multiplier)+int(factor))*multiplier)
        #        scrip   = master_config[TYPE][COIN]+"-"+str(strike)+"-"+master_config[TYPE][EXPIRY]
        #        val     = delta.get_current_value(scrip)
        #        if(val != -1 and val != 0): 
        #            val = float(val)
        #            break


        if(float(val)<MIN_BUY_PRE and ('buy' in buysell) and factor !=2):
            #local_log = local_log + " " +f"ATM value({val}) of {scrip} is less than 150 .so, not placing any Buy order."
            out[0] = -1
            out[1] = local_log
            print(f"ATM {val} less than {MIN_BUY_PRE} for buy order {scrip}.")
            return(out)
        if(float(val)<MIN_SELL_PRE and ('sell' in buysell)): # this is for premium of 0.03 US$.dont go below this 
            #local_log = local_log + " " +f"ATM value({val}) of {scrip} is less than 30 .so, not placing any sell  order."
            
            if(factor != -2):  # only for non-hedge orders 
                ctx         = scrip.split(seperator)
                ctx[2]      = str(int(ctx[2]) - 100) # go 100 points up and then come down
                ref_scrip   = seperator.join(ctx)

                for diff in range(0,300,50):
                    ctx         = ref_scrip.split(seperator)
                    ctx[2]      = str(int(ctx[2]) + diff)
                    ref_scrip   = seperator.join(ctx)
                    scrip       = ref_scrip
                    val         = delta.get_current_value(ref_scrip)
                    ctx[2]      = str(int(ctx[2]) - diff) # revert back for next iteration
                    ref_scrip   = seperator.join(ctx)

                    if(float(val) > MIN_SELL_PRE):
                        break
            
            if(float(val)< MIN_SELL_PRE and val != -1 and factor != -2):
                out[0] = -1
                out[1] = local_log
                print(f"ATM {val} less than 150 for sell order {scrip}")
                return(out)
        else:
            #print(f"value is {val} scrip is {scrip}")
            val = float(val)
                    
        #val         = float(delta.get_current_value(scrip))
        pid         = delta.get_product_id(scrip)
        new_factor  = factor*master_config[TYPE][tolerance]
        if('sell' in buysell): # keep half tolerance for sell orders.for hedge ,call with 2x so that this gives x 
            new_factor = float(new_factor)/2
            #if(factor == -2):
            #    new_factor = -1*new_factor

        BUY         = 0
        SELL        = 1
        
        response = -1
        limit = (1+new_factor)*float(val)
        #print(f"new factor {new_factor} val {val} lim {limit} factor {factor}")
        sl = (1+2*new_factor)*float(val)
        if(abs(factor)<2): # normal order ,factor is -1 or +1
            atm_strike      = 0
            scrip_strike    = 0
            if('buy' in buysell and master_context[TYPE][LAST_SL][BUY][VALUE] != 0): #recreate sl hit old order,this time with 5% tol
                scrip_strike= float(scrip.split('-')[2])
                atm_strike  = float(master_context[TYPE][LIVE][SCRIP].split(seperator)[2])
                if(factor*(atm_strike-scrip_strike) > 0.0 and abs(factor) == 1):
                    new_factor = new_factor/4 # 5% tolerance 
            #print(f"\nLastBuy:{master_context[TYPE][LAST_SL][BUY][VALUE]} atm:{atm_strike} scripstrike {scrip_strike} factor:{factor}")
        
            sl = (1+2*new_factor)*float(val)
            if(sl < 0.5):
                sl = 0.5
            limit = (1+new_factor)*float(val)
            if(limit< 1): # no use in placing such a low limit order .so, just return
                #print(f" limit price{limit} is less than 1 ,so no order is placed")
                limit = 1
                return(out)
        elif('sell' in buysell and abs(factor) == 2 and (val-limit) > PREMIUM_DIFF): # factor is -2.choose closest btwn 50 diff and tol
            limit = float(val) -PREMIUM_DIFF
            sl    = float(val) -(1.5*PREMIUM_DIFF)
            if(sl < 0.5):
                sl = 0.5

        elif('buy' in buysell and abs(factor) == 2 and (limit-val) > PREMIUM_DIFF): # factor is -2.choose closest btwn 50 diff and tol
            limit = float(val) +PREMIUM_DIFF
            sl    = float(val) +(1.5*PREMIUM_DIFF)
            if(sl < 0.5):
                sl = 0.5

        print(f"order: {buysell} {abs(tot_orders)} for {scrip} at sl:{sl} limit:{limit} val:{val}")
        response = -1

        response = deltaorder.stoploss_limit(pid,abs(tot_orders),buysell,sl,limit,float(val))

        if(response == -1):
            print(f"{buysell} order for  {scrip} failed")
            out[0] = response
            return(out)
        else:
            #print(response)
            accounts.parse_passive_orders(response,TYPE)
            print(f"\n\nCreate {buysell} order for type {TYPE}:")
            print(f"scrip : {scrip} BTC-fut: {master_context[SHEET][SPOT_LTP]}: val {val} limit {limit} ")
            print(f"Active:{master_context[TYPE][ACT]}")
            print(f"Passive:{master_context[TYPE][PAS]}")
            out[0] = 1
            local_log = local_log +" "+f"placed stoploss limit {buysell} for {scrip}:{val} with tolerance {new_factor}, sl {sl} and limit {limit}."
            if(factor == -2): # use hedge order data as last SL
                master_context[TYPE][LAST_SL][BUY][SCRIP] = scrip
                master_context[TYPE][LAST_SL][BUY][VALUE] = limit
            elif('buy' in buysell and factor != 2):
                master_context[TYPE][LAST_SL][SELL][SCRIP] = scrip
                master_context[TYPE][LAST_SL][SELL][VALUE] = limit

            #elif('sell' in buysell):
            #    master_context[TYPE][LAST_SL][SELL][SCRIP] = scrip
            #    if(abs(factor) == 2): # hedge order.mark this as SL value for 'BUY' order and not for 'SELL' order 
            #        master_context[TYPE][LAST_SL][BUY][VALUE] = limit

            ######## update passive list temporaily
            #if('buy' in buysell):
            #    size = 1
            #elif('sell' in buysell):
            #    size = -1
            #else:
            #    size = 0

            #item = [scrip,size,pid,sl,limit,pid,0]
            #master_context[TYPE][PAS].append(item)
            ########################################

            master_config[TYPE][STATUS] = 1
            local_log = local_log + " "+f"Last SL {buysell} is set to {scrip} and status for type {TYPE} is set."

            beep(1)
            out[1] = local_log
        return(out)
    # write a truth table and evaluate
    def decider (self,ctx_type,hedge):
        global CE
        global PE
        global ACT
        global PAS
        global master_context
        global master_config
        global ORDER_SCRIP
        global ORDER_LOT
        global ORDER_PID
        global ORDER_ID
        global ORDER_LTP
        global BUY
        global SELL
        global breakeven
        global SELL_CLOSE_VAL
        global VALUE

        local_log = ""
        SPOT_PRICE  = 0
        STATUS      = 0
        TYPE        = ctx_type
        ACTIVE_LTP  = 3
        PASSIVE_LTP = 3
        PID         = 3
        buy         = 0
        sell        = 0
        saved       = 0
        GAP         = 300
        
        hedge_list  = []

        sell_hedged = 0
        sell_hedge_list = []
        
        HEDGE_LTP   = 1
        ORDER_LMT   = 3  
        ORDER_PR    = 2
        val         = 0.0
        out         = [0,0,0]
        
        reponse     = 0
        if(TYPE%2 ==0):
            direction = -1
        elif(TYPE%2 ==1):
            direction = 1
        #print(master_context[TYPE][PAS])
        spot    = float(master_context[SHEET][SPOT_PRICE])
        #if(len(master_context[TYPE][ACT]) + len(master_context[TYPE][PAS])>4):
        #    print("####################################################")
        #    print("Order count beyond limit")
        #    beep(10)
        #    out[0] = 0
        #    out[1] = 0
        #    return(out)

        if(master_context[TYPE][ACT] != []):
            #print(f"Decider : active order:{master_context[TYPE][ACT]}")
            for order in master_context[TYPE][ACT]:
                breach = 0
                val     = float(delta.get_current_value(order[ORDER_SCRIP]))
                order[ACTIVE_LTP] = val
                if(order[ORDER_LOT]>0): # buy order
                    #master_context[TYPE][LAST_SL][BUY][ORDER_SCRIP] = order[ORDER_SCRIP] 
                    buy     = buy + int(order[ORDER_LOT])
                    local_log = local_log +" "+f"374 buy is {buy} sell {sell}"
                    #hedge   = hedge + int(order[ORDER_LOT])
                    
                    # all buy order need hedge sell ,so queue them and compare in passive list
                    item = []
                    item.insert(0,order[ORDER_SCRIP]) # to be compared with the passive list sell order
                    item.append(val)
                    if(hedge == 1):
                        if(hedge_list == []):
                            hedge_list.insert(0,item) # to be compared with the passive list sell order
                        elif(hedge_list != []):
                            hedge_list.append(item)
                        local_log = local_log +" "+f"383 hedged list {hedge_list}"

                elif(order[ORDER_LOT]<0): # sell order
                    sell    = sell + abs(int(order[ORDER_LOT]))
                    local_log = local_log +" "+f"387 sell is {sell} buy {buy} direction {direction}"
                    breach  = direction *(float(order[ORDER_SCRIP].split('-')[2]) + float(order[ORDER_LTP]) - spot)
                    
                    #if(breach > 0 and breach   >= (1.5*breakeven) and breach>GAP): # if strike goes beyond 750 points,move  on the winning leg
                    #    breach  = -1
                    #print(f"active ltp {order[ACTIVE_LTP]} sell close {SELL_CLOSE_VAL}")
                    if(order[ACTIVE_LTP] < SELL_CLOSE_VAL and int(order[ACTIVE_LTP]) != 0): # target (val = 15) hit...close the order
                        print(f"Sell close value hit {order}")  
                        master_context[TYPE][LAST_SL][SELL][ORDER_SCRIP] = 0
                        master_context[TYPE][LAST_SL][SELL][VALUE]       = 0
                        breach = -1 

                    if(breach <0):# and len(master_context[TYPE][ACT]) <2): #Sell order has become ATM and there is no active buy
                        local_log = local_log +"\n "+"ATM hit...bu market order"
                        local_log = local_log +"\n "+f" breach {breach} active count {master_context[TYPE][ACT]} scrip {order[ORDER_SCRIP]} spot {spot}"
                        # This is redundant but can be used for double confimation
                        #order[ORDER_LOT]         = delta.get_product_id(order[ORDER_SCRIP])

                        response = 0
                        
                        if(hedge == 1):
                            # cancel hedge before closing active order
                            cancel_hedge = 0
                            for p_order in master_context[TYPE][PAS]:
                                if((order[ORDER_SCRIP] in p_order[ORDER_SCRIP]) and (abs(order[ORDER_LOT]) == abs(p_order[ORDER_LOT]))):
                                    if(cancel_hedge != 1):
                                        print("line 460")
                                        response  = deltaorder.cancel(p_order[ORDER_PID],p_order[ORDER_ID])
                                        if(response != -1):
                                            master_context[TYPE][PAS] = [x_order for x_order in master_context[TYPE][PAS] if(x_order != p_order)]

                        response = deltaorder.market_order(order[PID],abs(order[ORDER_LOT]),'buy') # close order
                        print("placed order")
                        if(response != -1):
                            print(f"\n\n bu order placed successfull {response}")
                            print(f"\n\nlocal log is : \n{local_log}")
                            res = 0
                            master_context[TYPE][LAST_SL][SELL][VALUE]   = val
                            master_context[TYPE][LAST_SL][SELL][ORDER_SCRIP]   = order[ORDER_SCRIP]
                            master_context[TYPE][ACT] = [a_order for a_order in master_context[TYPE][ACT] if(a_order != order)]
                            #res = master_context[TYPE][ACT].remove(order) # remove cancelled order from the list
                            sell = sell - abs(int(order[ORDER_LOT])) # update total size
                            local_log = local_log +" "+f"397 sell is {sell} buy {buy}"
                            continue
                        else:
                            print(f"closing of breached order: {order} failed")
                    else:
                        sell_found = 1
                    ########################################added on 6/10##########################    
                    # all sell order need hedge buy ,so queue them and compare in passive list
                    val     = float(delta.get_current_value(order[ORDER_SCRIP]))
                    order[ACTIVE_LTP] = val
                    
                    #print(f"order before adding to sell {order}")
                    item = []
                    item.insert(0,order[ORDER_SCRIP]) # to be compared with the passive list buy order
                    item.append(val)
                    item.append(float(order[ORDER_ENT]))
                    if(hedge == 1):
                        if(sell_hedge_list == []):
                            sell_hedge_list.insert(0,item) # to be compared with the passive list buy order
                        elif(sell_hedge_list != []):
                            sell_hedge_list.append(item)
                    ###########################################################################
                    #master_context[TYPE][LAST_SL][SELL][ORDER_SCRIP] = order[ORDER_SCRIP] 
                    local_log = local_log +" "+f"401 sell is {sell} buy {buy}"
        saved = 0
        if(master_context[TYPE][PAS] != []): # Passive orders
            for order in master_context[TYPE][PAS]:
                breach = 0
                if(order[ORDER_LOT]>0): # buy order
                    ##############################################added on 6/10 ##########################
                    sell_hedge_check = 0
                    for hedge_order in sell_hedge_list:
                        local_log = local_log +" "+f"sell hedge order {hedge_order} order {order}"
                        #print(f"sell hedge order {hedge_order} order {order}")
                        if(hedge_order[ORDER_SCRIP] in order[ORDER_SCRIP] and sell_hedge_check == 0): # last check to handle duplicates
                            sell_hedge_check = 1
                            sell_hedged = 1    
                            #out = 0
                            #print(f"buy:is {order[ORDER_LMT]} -{hedge_order[HEDGE_LTP]} > 50 ? {hedge_order} {order}")
                            val_now = float(order[ORDER_LMT])
                            response = 0
                            if((val_now-hedge_order[HEDGE_LTP]>50.0) and val_now>(hedge_order[ORDER_PR]-10)):
                                print("line 513")
                                response  = deltaorder.cancel(order[ORDER_PID],order[ORDER_ID])
                                if(response == -1):
                                    print(f"cancel of breached hedge buy order: {order} failed")
                                else:
                                    print(f"Cancelled hedge order: {order[ORDER_SCRIP]}")
                                    res = 0
                                    master_context[TYPE][PAS] = [p_order for p_order in master_context[TYPE][PAS] if(p_order != order)]
                                    #res = master_context[TYPE][PAS].remove(order) # remove cancelled order from the list
                                    time.sleep(2)
                                    SL_TOL  = 2
                                    factor  = 2
                                    local_log = local_log +" "+"Placing new buy order as hedge"
                                    print("Buy order place")
                                    response = util.limit_order_create('buy',order[ORDER_SCRIP],TYPE,2,order[ORDER_LOT],SL_TOL)
                            # Even if there is no update in hedge order,checked order in hedge list has to be removed to avoid recheck
                            if(response != -1 or (hedge_order[HEDGE_LTP]-float(order[ORDER_LMT]) <= 50.0)):
                                sell_hedge_list = [a_order for a_order in sell_hedge_list if(a_order != hedge_order)]

                        else:
                            continue

                    ######################################################################################
                    breach = 0
                    if(sell_hedge_check == 0):
                        buy     = buy + int(order[ORDER_LOT])
                        local_log = local_log +" "+f"412 buy is {buy} sell {sell}"
                        breach  = direction *(float(order[ORDER_SCRIP].split('-')[2]) - spot)

                    if(breach >= (1.5*breakeven) and breakeven != 0): # move it closer to ATM
                        local_log = local_log +" "+f"breach {breach} dir {direction} scrip {order[ORDER_SCRIP]} spot {spot} breakevn {breakeven}"
                        print("line 540")
                        response  = deltaorder.cancel(order[ORDER_PID],order[ORDER_ID])
                        if(response != -1):
                            local_log = local_log +" "+f"cancelled breached order :{order} as it is > 1.5 breakeven"
                            buy = buy - int(order[ORDER_LOT]) # update total size
                            #res = 0
                            master_context[TYPE][PAS] = [p_order for p_order in master_context[TYPE][PAS] if(p_order != order)]
                            #res = master_context[TYPE][PAS].remove(order) # remove cancelled order from the list
                            local_log = local_log +" "+f"418 buy is {buy} sell {sell}"
                        else:
                            local_log = local_log +" "+f"cancel of breached passive buy order: {order} failed"
                        
                elif(order[ORDER_LOT]<0):
                    hedge_check = 0
                    local_log = local_log +" "+f"\n424 hedged list {hedge_list}"
                    for hedge_order in hedge_list:
                        local_log = local_log +" "+f"\nhedge order {hedge_order} order {order} hedge check {hedge_check}"
                        if(hedge_order[ORDER_SCRIP] in order[ORDER_SCRIP] and hedge_check == 0): # last check to handle duplicates
                            hedge_check = 1
                            saved = 1    
                            #out = 0
                            print(f"sell:is {hedge_order[HEDGE_LTP]} - {order[ORDER_LMT]} > 50 ?")
                            response = 0
                            if(hedge_order[HEDGE_LTP]-float(order[ORDER_LMT]) > 50.0):
                                print("line 568")
                                response  = deltaorder.cancel(order[ORDER_PID],order[ORDER_ID])
                                if(response == -1):
                                    print(f"cancel of breached hedge sell order: {order} failed")
                                else:
                                    print(f"Cancelled order: {order[ORDER_SCRIP]}")
                                    #res = 0
                                    master_context[TYPE][PAS] = [p_order for p_order in master_context[TYPE][PAS] if(p_order != order)]
                                    #res = master_context[TYPE][PAS].remove(order) # remove cancelled order from the list
                                    time.sleep(2)
                                    SL_TOL  = 2
                                    factor  = -2
                                    local_log = local_log +" "+"Placing new order as hedge"
                                    #sometimes this call is not getting triggered in this loop and getting triggered onl in 
                                    #the next scheduler call, during such case, if ltp drops , 
                                    #the new sl < old sl,which destroys the purpose of checking >50 condition here ..check this  
                                    response = util.limit_order_create('sell',order[ORDER_SCRIP],TYPE,-2,order[ORDER_LOT],SL_TOL);
                            if(response != -1 or (hedge_order[HEDGE_LTP]-float(order[ORDER_LMT]) <= 50.0)):
                            # Even if there is no update in hedge order,checked order in hedge list has to be removed to avoid recheck
                                hedge_list = [a_order for a_order in hedge_list if(a_order != hedge_order)]

                        else:
                            continue
                    
                    breach = 0
                    if(hedge_check == 0):
                        sell    = sell + abs(int(order[ORDER_LOT]))
                        local_log = local_log +" "+f"443 sell is {sell} buy {buy}"
                        local_log = local_log +" "+f"492 hedged list {hedge_list} pas list {master_context[TYPE][PAS]}"
                        breach  = direction *(float(order[ORDER_SCRIP].split('-')[2]) - spot)
                    
                        #if(breach > 0 and breach >= (1.5*breakeven) and breach >500): # if strike up by 500 points, move on the winning leg
                        #    breach  = -1

                        if(breach<0): # ensure this is NOT a hedge order
                            count = 0
                            for a_order in master_context[TYPE][ACT]:
                                if(order[ORDER_SCRIP] in a_order[ORDER_SCRIP] and a_order[ORDER_LOT] > 0): 
                                    count = count + int(a_order[ORDER_LOT])
                            if(count != 0): # active bu is present .so, hedge is more likely
                                count = count - abs(int(order[ORDER_LOT])) # discount present order size
                                for p_order in master_context[TYPE][PAS]:
                                    if(order[ORDER_SCRIP] in p_order[ORDER_SCRIP] and p_order[ORDER_LOT] < 0): 
                                        count = count + int(p_order[ORDER_LOT])
                                if(count == 0):
                                    breach = 0 # this is a hedge order ,so dont check for breach
                        
                        breach  =0 ## added to avoid alterations of passive sell
                        if(breach <0): #Sell order has become ATM
                            response  = deltaorder.cancel(order[ORDER_PID],order[ORDER_ID]) # close order
                            if(response != -1):
                                print(f"Cancelled Sell order {order[ORDER_SCRIP]} ,as it has become ATM")
                                sell = sell - abs(int(order[ORDER_LOT])) # update total size
                                local_log = local_log +" "+f"453 sell is {sell} buy {buy}"
                            else:
                                print(f"cancel of breached passive sell order: {order} failed")
                            continue

                #val                 = float(delta.get_current_value(order[ORDER_SCRIP]))
                #order[ORDER_LTP]    = val

        
        if(saved !=1 and hedge_list!=[] and hedge ==1):
            for order in hedge_list:
                #create sell order
                SL_TOL  = 2
                factor  = -2
                response = util.limit_order_create('sell',order[ORDER_SCRIP],TYPE,-2,int(master_config[SHEET][LOT]),SL_TOL);
                #if(response != -1):
                #    item = [order[ORDER_SCRIP],order[ORDER_LOT],0,0,0,0]
                #    if(header.master_context[TYPE][PAS] != []):
                #        master_context[TYPE][PAS].append(item)
                #    else:
                #        master_context[TYPE][PAS].insert(0,item)

        #################################### added on 6/10 #########################################
        if(sell_hedged !=1 and sell_hedge_list!=[] and hedge == 1):
            for order in sell_hedge_list:
                #create sell order
                SL_TOL  = 2
                factor  = 2
                print(f"create new buy {sell_hedge_list}")
                response = util.limit_order_create('buy',order[ORDER_SCRIP],TYPE,factor,int(master_config[SHEET][LOT]),SL_TOL);
        #################################### added on 6/10#########################################        
        if(buy ==0):
            if(sell == 0):
                sell= int(master_config[SHEET][LOT])
            else:
                buy  = abs(int(sell))
                sell = buy - abs(int(sell))
                local_log = local_log +" "+f"490 buy {buy} {sell}"

            buy = int(master_config[SHEET][LOT])
            local_log = local_log +" "+f"475 buy {buy} {sell}"
        elif(sell == 0):
            sell    = int(master_config[SHEET][LOT])
            buy     = buy - abs(sell)
            local_log = local_log +" "+f"477 buy {buy} {sell}"
        else: 
            local_log = local_log +" "+f"478 buy {buy} {sell}"
            val = buy
            buy = abs(int(sell)) - int(buy)
            sell = val - abs(int(sell))
            local_log = local_log +" "+f"482 buy {buy} {sell}"
        

        local_log = local_log +" "+f"487 buy {buy} {sell}"
        out[0] = int(buy)
        out[1] = int(sell)
        out[2] = local_log
        
        #print('\n')
        #print(local_log)
        
        if(master_context[TYPE][ACT] != [] or master_context[TYPE][PAS] != []):
            master_config[TYPE][STATUS]  = 1
        return(out)

    def cancel_opposite_orders(self):
        global CE
        global PE
        global master_context
        global ORDER_PID #4 this is for passive orders
        PID = 3 # this is for active order 
        global ORDER_ID #5
        global ORDER_SCRIP
        global ORDER_LTP
        global ORDER_LOT
        global deltaorder
        local_log = ""
        out = [0,""]
        global ACT
        global PAS
        ACTIVE_LTP  = 3
        PASSIVE_LTP = 3
        TYPE = 0
        net_pe = 0
        net_ce = 0

        if(master_context[PE][ACT] != [] and master_context[CE][ACT] != []):
            for pe_order in master_context[PE][ACT]:
                if(pe_order[ORDER_LOT]>0):
                    #pe_val = float(delta.get_current_value(pe_order[ORDER_SCRIP]))
                    #pe_order[ACTIVE_LTP] = pe_val
                    pe_val = pe_order[ACTIVE_LTP]
                    net_pe = pe_val - float(pe_order[ORDER_LTP]) # positive if on profit

                for ce_order in master_context[CE][ACT]:
                    if(ce_order[ORDER_LOT]>0):
                        #ce_val = float(delta.get_current_value(ce_order[ORDER_SCRIP]))
                        #ce_order[ACTIVE_LTP] = ce_val
                        ce_val = ce_order[ACTIVE_LTP]
                        net_ce = ce_val - float(ce_order[ORDER_LTP]) # positive if on profit

                    #print(f"pe order {pe_order}")
                    if(net_pe < 0 and net_pe < 0.5*net_ce and net_ce != 0): # PE active buy is on high loss
                        local_log = local_log + " "+ f"pe buy order {pe_order} is on loss.,closing it."
                        response = deltaorder.market_order(pe_order[PID],abs(pe_order[ORDER_LOT]),'sell') # close order
                        if(response != -1):
                            print(f"\n\nlocal log is \n{local_log}")
                            #scrip = pe_order[ORDER_SCRIP]
                            master_context[PE][ACT] = [a_order for a_order in master_context[PE][ACT] if(a_order != pe_order)]
                            #master_context[PE][ACT].remove(pe_order)
                            TYPE = PE

                    if(net_ce < 0 and net_ce < 0.5*net_pe and net_pe != 0): # CE buy is on high loss
                        local_log = local_log + " "+ f"ce buy order {ce_order} is on loss.,closing it."
                        response = deltaorder.market_order(ce_order[PID],abs(ce_order[ORDER_LOT]),'sell') # close order
                        if(response != -1):
                            print(f"\n\nlocal log is \n{local_log}")
                            #scrip = ce_order[ORDER_SCRIP]
                            master_context[CE][ACT] = [a_order for a_order in master_context[CE][ACT] if(a_order != ce_order)]
                            #master_context[CE][ACT].remove(ce_order)
                            TYPE = CE

                    if(TYPE != 0): # clear only the hedge
                        for p_order in master_context[TYPE][PAS]:
                            if(scrip in p_order[ORDER_SCRIP]):
                                response  = deltaorder.cancel(p_order[ORDER_PID],p_order[ORDER_ID])
                                if(response != -1):
                                    local_log = local_log + " "+ f"clearing the passive order {p_order} associated with the failing order."
                                    master_context[TYPE][PAS] = [a_order for a_order in master_context[TYPE][PAS] if(a_order != p_order)]
                                    #master_context[TYPE][PAS].remove(p_order)
                                    out[0] = -1
                                

                    out[1] = out[1] + local_log
        return(out)

    def check_breach(self,order_list,act_pas,direction,ctx_type):
        global ORDER_PID #4
        global ORDER_ID #5
        global ORDER_SCRIP
        global ORDER_LTP
        global master_config
        global master_context
        global breakeven
        global ACT
        global PAS
        local_log = ""
        out = [0,""]

        TYPE        = ctx_type

        LIVE        = 0
        SCRIP       = 0
        SIZE        = 1
        SL_TOL      = 2
        SHEET       = 0
        SPOT_PRICE  = 0
        STATUS      = 0
        PID         = 3
        
        
        total_orders= 0
        order_breach= 0
        response    = 0
        spot        = 0
        cancel      = 0

        if(order_list!=[]):
            for order in order_list: # format ['C-BTC-34750-120522', 1, -1.0,pid]
                total_orders = total_orders + order[SIZE]
                spot = float(master_context[SHEET][SPOT_PRICE])
                breach = direction *(float(order[SCRIP].split('-')[2]) - spot)
                local_log = local_log +" "+(f"{order[SIZE]}: is breach {breach} > breakeven {1.5*breakeven} dir {direction}... is scrip{order[SCRIP]} <spot {spot}")
                if(breach >= (1.5*breakeven) and breakeven != 0): # if strike goes beond 750 points, move up b 250 on the winning leg
                    breach = -1
                    
                if(order[SIZE] < 0 and breach <0): #Sell order has become ATM
                    if(act_pas == ACT):
                        local_log = local_log + "\n"+ f"sell order {order[SCRIP]} breached spot price {spot}."
                        local_log = local_log + "\n"+ f"close Active {order[SCRIP]} with a new buy order ."
                        response = deltaorder.market_order(order[PID],abs(order[SIZE]),'buy') # close order
                        if(response != -1):
                            print(f"\n\nlocal log is \n{local_log}")
                            total_orders = total_orders - order[SIZE] # update total size

                        order_breach = 1
                        cancel  = 0 # order is either closed or cancelled
                    elif(act_pas == PAS and breach != -1): # second case needs to be removed after testing
                        cancel      = 0
                        # if this is a hedge for active buy,cancel only the order is beyond tolerance level
                        for a_order in master_context[TYPE][ACT]:
                            if(order[ORDER_SCRIP] in a_order[ORDER_SCRIP]):
                                factor = float(1-float(master_config[TYPE][SL_TOL])) # factor = 0.8
                                sl = factor* float(a_order[ORDER_LTP])   # 0.8*ltp
                                if(float(order[ORDER_LTP]) >= sl): # stoploss 
                                    cancel = 1
                                else:
                                    local_log = local_log+"\n"+f"Adjust sl order {order[ORDER_SCRIP]} from {order[ORDER_LTP]} to <{sl}."
                        if(cancel == 0):
                            #print(f"cancel  order: {act_pas} for {order[ORDER_SCRIP]}")
                            local_log = local_log + "\n"+ f"sell order {order[SCRIP]} breached spot price {spot}."
                            local_log = local_log + "\n"+ f"cancel passive sell order: {order[ORDER_SCRIP]}."
                            response  = deltaorder.cancel(order[ORDER_PID],order[ORDER_ID])
                            if(response != -1):
                                print("\norder{order} breached spot{spot} ,so cancelling ")
                                total_orders = total_orders - order[SIZE] # update total size


                    if(response != -1):
                        out[0] = 0
                #if(order[SIZE] > 0 or cancel !=0): # no cancellation done 
        out[0]  = total_orders
            #local_log = local_log +" "+ f"total orders is {total_orders}."
            #if(order_breach == 1 and act_pas == ACT): # remove corresponding buy order too
            #    for order in order_list:
            #        if(order[SIZE] > 0):
            #            local_log = local_log + " "+ f"sell order {order[ORDER_SCRIP]} closed on breach.closing its active buy leg."
            #            response = deltaorder.market_order(order[PID],order[SIZE],'sell') # close order
            #            total_orders = total_orders - order[SIZE]
            #            out[0] = total_orders
        
        out[1] = local_log
        return(out)

    def hedge_active(self,ctx):
        global ORDER_PID #4
        global ORDER_ID #5
        global ORDER_SCRIP
        global ORDER_LTP
        global master_config
        global master_context
        
        ACTIVE_LTP  = 3
        PASSIVE_LTP = 3
        STATUS      = 0
        TOL         = 1
        SL_TOL      = 2
        SPOT_TOL    = 3
        PREMIUM_DIFF= 50.0
        SHEET       = 0
        SPOT_LTP    = 0

        global ACT
        global PAS
        local_log = ""
        out = [0,""]

        TYPE = ctx
        # Hedge Active Buy orders alone
        if(master_context[TYPE][ACT] != []):
            for a_order in master_context[TYPE][ACT]:
                hedge = 0
                if(a_order[ORDER_LOT] > 0): # Buy orders
                    #print(f"hdged {a_order}")
                    for p_order in master_context[TYPE][PAS]:
                        #print(f"p_order {p_order} a_order {a_order}")
                        if(p_order[ORDER_LOT] <0 and a_order[ORDER_SCRIP] in p_order[ORDER_SCRIP]):
                            #if(float(a_order[ACTIVE_LTP])*(1-master_config[TYPE][SL_TOL]) > float(p_order[PASSIVE_LTP])):
                            # initial hedge is 10% but if in profit change it to 50 points diff  
                            if(float(a_order[ACTIVE_LTP]) - float(p_order[PASSIVE_LTP]) > PREMIUM_DIFF): 
                                #print(f"Calling cancel act = {float(a_order[ACTIVE_LTP])} pas = {float(p_order[PASSIVE_LTP])} diff {(float(a_order[ACTIVE_LTP]) - float(p_order[PASSIVE_LTP]))}")
                                response  = deltaorder.cancel(p_order[ORDER_PID],p_order[ORDER_ID])
                                if(response == -1):
                                    local_log = local_log + " "+ f"deleting the passive hedge order {p_order} failed."
                                    hedge = 1
                                elif(response != -1):
                                    order_placed = 1
                                    print(f"\nPremium diff > 50 a-order : {a_order} Cancel order {p_order}")
                                    local_log = local_log + " "+ f"cleared passive hedge for {a_order[ORDER_SCRIP]}."
                                    hedge = 0
                            else:
                                #print("Hedged Already")
                                hedge = 1
                                break
                    if(hedge == 0): # Hedge required
                        factor = -1
                        local_log = local_log+" " + f"hedge for {a_order[ORDER_SCRIP]} not found in {master_context[TYPE][PAS]},"
                        # pass factor*2 here and reduce SL_TOL into half ,to balance , in limit_order_create function
                        factor = factor*2
                        print(f"\n\nCreate Hedge order for type {TYPE}:")
                        out = util.limit_order_create('sell',a_order[ORDER_SCRIP],TYPE,factor,a_order[ORDER_LOT],SL_TOL);
                        local_log = local_log + '\n' + out[1]
                        if(out[0] == -1):
                            print(f"Hedge for order {a_order} failed")
                            #out[1] = local_log
                            #return(out)
                        else:
                            order_placed = 1
                            local_log = local_log+" " + f"placed sell order {a_order[ORDER_SCRIP]} " + '\n'
                            
                        out[1] = local_log
        return(out)
    
    def expiry_gains(self):
        global master_context
        global PE
        global CE
        global ACT
        global PAS
        global max_type
        global ORDER_LOT
        global ORDER_LTP
        global gains
        global seperator
        global LIVE

        SHEET       = 0
        SPOT_LTP    = 0
        ACTIVE_LTP  = 3

        gains = 0
        direction = -1
        out = [0,0,0] # gains,ce_breach,pe_breach 
        for i in range(1,max_type+1): #Daily CE and PE Alone
            direction = direction * -1 # 1 for CE and -1 for PE
            for a_order in master_context[i][ACT]:
                if(a_order[ORDER_LOT] >0):
                    gains = gains - (float(a_order[ORDER_LTP]) - float(a_order[ACTIVE_LTP]))
                elif(a_order[ORDER_LOT] <0):
                    strike = float(a_order[ORDER_SCRIP].split(seperator)[2])
                    if(direction*(strike - float(master_context[SHEET][SPOT_LTP])) > 0):
                        gains = gains + float(a_order[ORDER_LTP])
                        out[i] = 1
                    else:
                        gains = gains + (float(a_order[ACTIVE_LTP]) - float(a_order[ORDER_LTP]))
                        out[i] = -1
            for p_order in master_context[i][PAS]:
                if(p_order[ORDER_LOT] <0):
                    strike = float(p_order[ORDER_SCRIP].split(seperator)[2])
                    if(direction*(strike - float(master_context[SHEET][SPOT_LTP])) > 0):
                        gains = gains + float(a_order[ORDER_LTP])
        out[0] = float(gains)
        return(out)

    def get_best_orders(self,odr_ctx):
        global util
        global master_context
        global ACT
        global PAS
        global ORDER_LOT
        global ORDER_PID

        TYPE    = odr_ctx
        gains   = 0
        status  = util.expiry_gains()
        if(status[TYPE] == 1):
            if(len(master_context[TYPE][ACT])<2): # only sell order and that has become ATM
                # in this case ,make the passive hedge buy as active 
                for p_order in master_context[TYPE][PAS]:
                    if(p_order[ORDER_LOT]>0):
                        PID = p_order[ORDER_PID]
                        response  = deltaorder.cancel(p_order[ORDER_PID],p_order[ORDER_ID])
                        if(response != -1):
                            master_context[TYPE][PAS] = [x_order for x_order in master_context[TYPE][PAS] if(x_order != p_order)]

                        response = deltaorder.market_order(PID,abs(order[ORDER_LOT]),'buy') # close order

        



class get_config:
    global log
    def __init__(self):
        self.log = log

    def read_config(self):
        global master_config
        global CE
        global PE
        global CEM
        global PEM
        COIN   = 4
        EXPIRY = 5


        item = []
        coin = googlesheet.coin_type()
        item.append(coin)

        item.append( googlesheet.expiry_type())
        item.append( googlesheet.frequency_value())
        item.append( googlesheet.strategy_type())
        item.append( googlesheet.hedged())
        item.append( googlesheet.get_baseurl())
        item.append( googlesheet.get_apikey())
        item.append( googlesheet.get_apisecret())
        item.append( googlesheet.get_lotsize())

        master_config[CE][COIN]  = "C-"+ coin
        master_config[CEM][COIN] = "C-"+ coin
        master_config[PE][COIN]  = "P-"+ coin
        master_config[PEM][COIN] = "P-"+ coin
        
        master_config[CE][EXPIRY]  =  gettimer.next_expiry()
        master_config[PE][EXPIRY]  =  gettimer.next_expiry()
        master_config[CEM][EXPIRY] =  gettimer.next_month_expiry()
        master_config[PEM][EXPIRY] =  gettimer.next_month_expiry()
         
        log.info("AM-2000")
        return(item)

class strategy_run: # modif to new ds
    global log
    global delta 
    global trade_context


    status          = 0
    pl              = [0,0,0,0]                  #[sell PE,sell CE,buy PE, buy CE]

    def __init__(self):
        log.info("AM-3000")

    # ##################################################################
    # status_check(context type(arguments: 1<=integer <=4)) 
    # check all passive orders without pair active order and delete them  
    # ##################################################################
    @classmethod
    def status_check(self,ctx_type): # 1 ce,2 pe, 3 cem, 4 pem
        global master_context
        # orders
        global ACT
        global PAS
        global ORDER_PID #4
        global ORDER_ID #5
        
        TYPE = ctx_type       # 1 ce,2 pe, 3 cem, 4 pem

        global deltaorder

        response = 0
        if(master_context[TYPE][ACT] == [] and master_context[TYPE][PAS] != []): # active 0, passive != 0: cancel all passive orders
            print("Deleting all passive orders as there is no active order")
            for order in master_context[TYPE][PAS]:
                response = -1
                response  = deltaorder.cancel(order[ORDER_PID],order[ORDER_ID])
                if(response != -1):
                    response = 0
        return(response)
    
    ###################################################################################################
    # hedge_live_orders(context type(arguments: 1<=integer <=4))
    # check passive order pair for all  active orders.if not present, create new passive order
    # if passive order is present, adjust them as trailing Stop loss orders 
    ###################################################################################################
    @classmethod
    def hedge_live_orders(self,ctx_type,buysell): # pass sell to hedge buy orders ,20% premium tol for day
        global deltaorder
        global master_context
        global ACT
        global PAS
        global context
        
        TYPE        = ctx_type       # 1 ce,2 pe, 3 cem, 4 pem

        STATUS      = 0
        TOL         = 1
        SL_TOL      = 2
        SPOT_TOL    = 3

        global ORDER_SCRIP #0
        global ORDER_LOT #1
        global ORDER_LTP #2
        global ORDER_PID #4
        global ORDER_ID #5
        order_flag = 0
        
        for a_order in master_context[TYPE][ACT] :
            step = float(float(a_order[ORDER_LTP])*master_config[TYPE][SL_TOL]/2) # divide b 2 as mark=tol limit=2*tol 
            if(step < 0.1):  # if the LTP is less than 1, no need to hedge
                continue                        
            if(a_order[ORDER_LOT] > 0):
                factor = -1
            elif(a_order[ORDER_LOT]<0):
                factor = 1
            else: 
                print(f"Lot size of active order: {a_order} is corrupt")

            adjust_lot  = a_order[ORDER_LOT] 
            total_lot   = 0
            for p_order in master_context[TYPE][PAS]: 
                if (a_order[ORDER_SCRIP] in p_order[ORDER_SCRIP]):
                    new_sl = float((1+(factor*master_config[TYPE][SL_TOL]))* float(a_order[ORDER_LTP]))
                    if((factor*(float(a_order[ORDER_LTP])-new_sl)>0) and (float(p_order[3])-new_sl)<1): # 1.2* p_order and old sl ~new sl
                        response = deltaorder.cancel(p_order[ORDER_PID],p_order[ORDER_ID])
                        if(response == -1):
                            print(f"cancel order for {p_order} failed")
                            return(-1)
                        else:
                            print(f"\n\ncancel order: {buysell} for {a_order} , p order:{p_order}")
                            order_flag = 1
                    else:
                        if((total_lot+ p_order[ORDER_LOT] > a_order[ORDER_LOT])): # excess of hedges
                            response = deltaorder.cancel(p_order[ORDER_PID],p_order[ORDER_ID]) 
                            if(response == -1):
                                print(f"cancel excess order for {p_order} failed")
                                return(-1)
                            else:
                                print(f"\n\nExcess hedge cancel: {buysell} for {a_order} , p order:{p_order}")
                                #print(f"cancel excess order: {buysell} for {a_order[ORDER_SCRIP]}")
                                order_flag = 1
                        else:
                            total_lot = total_lot + p_order[ORDER_LOT]
                            adjust_lot = a_order[ORDER_LOT] + total_lot 

            if(adjust_lot>0):
                val         = float(a_order[ORDER_LTP])
                pid         = delta.get_product_id(a_order[ORDER_SCRIP])
                new_factor   = factor*master_config[TYPE][TOL] 
                #print(f"hedge order: {buysell} {adjust_lot} for {a_order[ORDER_SCRIP]} at {val}")
                response = deltaorder.stoploss_limit(pid,adjust_lot,buysell,(1+2*new_factor)*val,(1+new_factor)*val,val)
                if(response == -1):
                    print(f"hedge order for Active order: {a_order} failed")
                    return(-1)
                else:
                    order_flag = 1
                    beep(1)
        if(order_flag ==1): # if a new order is placed
            master_config[TYPE][TOL]     = float(0.75*master_config[TYPE][TOL])
            master_config[TYPE][SL_TOL]  = float(0.75*master_config[TYPE][SL_TOL])

            out     = accounts.get_live_orders()
            result  = context.update_orders(TYPE)
            for order in master_context[TYPE][ACT]: # format ['C-BTC-34750-120522', 1, -1.0]
                ltp    = float(delta.get_current_value(order[SCRIP]))                        # update LTP
                if(ltp == -1):
                    print("Update ltp for active order "+order[SCRIP]+ "failed")
                    log.error("AM-4014-"+order[SCRIP])
                    return(-1)
                order[ORDER_LTP] = ltp
            
        return(0)
    

    ###################################################################################################
    # place_dir_orders(context type(arguments: 1<=integer <=4),buysell ('buy' or 'sell'))
    # if ITM order exists,add one more .else place a new ATM order
    # update the context 
    ###################################################################################################
    @classmethod
    def place_dir_orders(self,ctx_type,buysell): # CE 1 ,PE 2 CEM 3 PEM 4 
        global ACT	
        global PAS	
        global master_context
        global master_config 
        global context
        global ORDER_LTP

        TYPE        = ctx_type

        LIVE        = 0
        SCRIP       = 0
        SHEET       = 0
        LOT         = 8
        NEW_ATM     = 1
        OLD_ATM     = 2
        TOL         = 1
        SPOT_PRICE  = 0 
        lot_size    = master_config[SHEET][LOT]
        order_flag  = 0
        active_flag = 0
        order_ctx   = master_context[TYPE][LIVE]
        if(master_context[TYPE][ACT] != []):
            active_flag = 1
        
        result = 0
        dir_sign = -1
        for i in range(TYPE): #1:1 ,2:1,3:-1,4:1
            dir_sign = dir_sign * -1

        if(float(order_ctx[NEW_ATM])>=(1+master_config[TYPE][TOL])*float(order_ctx[OLD_ATM])): # 1.2 * local_c
            print(f" spot {str(master_context[SHEET][SPOT_PRICE])} order {str(order_ctx[NEW_ATM])} tol {str(master_config[TYPE][TOL])}")
            if(active_flag == 0 and (dir_sign*(master_context[SHEET][SPOT_PRICE] - float(order_ctx[NEW_ATM]))>=float(master_config[TYPE][TOL]))):
                pid = 0
                val = 0
                pid = delta.get_product_id(master_context[TYPE][LIVE][SCRIP])        # ce scrip
                val = float(order_ctx[NEW_ATM])
                if(pid !=0 and val != 0):
                    response = []
                    #response = deltaorder.market_order(pid,lot_size,buysell)             # buy order
                    if(response != []):
                        beep(1)
                        order_flag = 1
                        print("order {master_context[TYPE][LIVE][SCRIP]} spot changed from {order_ctx[NEW_ATM]} to {master_context[SHEET][SPOT_PRICE]} ")
                
            elif(active_flag != 0):
                scrip_str = ''
                #print("buy at ATM or add one lot to the existing buy order,whichever is lower")
                for order in master_context[TYPE][ACT]:
                    strike = float(order[SCRIP].split('-')[2])                            # strike price of active order
                    if(dir_sign* (float(master_context[SHEET][SPOT_PRICE]) - strike) >0):
                        scrip_str = order[SCRIP]  # scrip for existing order
                    else:
                        scrip_str = order_ctx[SCRIP]       # ATM
                if(scrip_str != ''):
                    pid = 0
                    val = 0
                    pid = delta.get_product_id(scrip_str)        # ce scrip
                    val = delta.get_current_value(scrip_str)

                    if(pid != 0 and val != 0):
                        print("add "+ buysell+" " +str(lot_size)+ " lot of " + scrip_str + " for " + str(val))
                        response = []
                        #response = deltaorder.market_order(pid,lot_size,buysell) # buy order
                        if(response != [] ):
                            beep(1)
                            order_flag = 1
                            print("add {master_context[TYPE][LIVE][SCRIP]} spot changed from {order_ctx[NEW_ATM]} to {master_context[SHEET][SPOT_PRICE]} ")
                
                    else:
                        print(f"pid {pid} or value {val} is 0 for {scrip_str}")
            if(order_flag == 1):
                result = accounts.get_order_history()
                if(result != -1):
                    result  = -1
                    result  = context.update_orders(TYPE)
                    if(result != -1):
                        for order in master_context[TYPE][ACT]: # format ['C-BTC-34750-120522', 1, -1.0]
                            ltp    = float(delta.get_current_value(order[SCRIP]))                        # update LTP
                            if(ltp == -1):
                                print("Update ltp for active order "+order[SCRIP]+ "failed")
                                log.error("AM-4014-"+order[SCRIP])
                                return(-1)
                            order[ORDER_LTP] = ltp

                    else:
                        print(f"Update context failed for type {TYPE}") #1 CE, 2 PE ,3 CEM, 4 PEM
                else:
                    print(f"active order update, after placing order, failed")
                    result = -1
            elif(active_flag == 0):
                result  = context.update_context(TYPE)
        return(result)
        

    def directional_call(self,context): # buy options
        global master_config
        global master_context
        global CE 
        global ACT
        global PAS
        LIVE    = 0
        SCRIP   = 0
        NEW_ATM = 1
        OLD_ATM   = 2
        global ORDER_LTP   #2
        global ORDER_SCRIP #0

        global SPOT_PRICE #0
        global log
        global delta
        #global trade_context

        TYPE        = 1 #CE 
        STATUS      = 0
        TOL         = 1
        SL_TOL      = 2
        SPOT_TOL    = 3
        #CE_DIR      = 1
        #response1   = []
        log.info("AM-3010")
        exp = next_expiry()
        search_str = master_config[TYPE][COIN]
        
        if(master_context[TYPE][ACT]!=[]):
            # Update LTP for active orders
            for order in master_context[TYPE][ACT]: # format ['C-BTC-34750-120522', 1, -1.0]
                ltp    = float(delta.get_current_value(order[SCRIP]))                        # LTP
                if(ltp == -1):
                    print("Update ltp for active order "+order[SCRIP]+ "failed")
                    log.error("AM-4014-"+order[SCRIP])
                    return(-1)
                pl = (float(order[ORDER_LTP])-ltp)/float(order[ORDER_LTP])   # PL percentage
                if(pl < 0.0 or pl< master_config[TYPE][SL_TOL]): #check if order is in profit or within SL range
                    master_config[TYPE][STATUS]  = 1
                
                order[ORDER_LTP] = ltp 

        # check for stale passive orders and delete them
        result = strategy_run.status_check(TYPE)  # pass CE as 1 , returns 0 if active order is Null
        if(result != 0):
            print("Could not delete weekly stale passive orders..Order list : {master_context[CE][PAS]}")
            return(-1)
        if(master_config[TYPE][STATUS] == 0 and result == 0):
            master_config[TYPE][STATUS]  = 1
        
        elif(master_config[TYPE][STATUS] == 1):
            master_context[TYPE][LIVE][OLD_ATM] = master_context[TYPE][LIVE][NEW_ATM] # store new ce scrip & val in arr[2] and arr[3] resp
            master_context[TYPE][LIVE][NEW_ATM] = delta.get_current_value(master_context[TYPE][LIVE][SCRIP]) # reuse for new ltp for ce

            result = strategy_run.place_dir_orders(TYPE,'buy') 
            master_context[TYPE][LIVE][OLD_ATM] = master_context[TYPE][LIVE][NEW_ATM] # update old ltp to avoid looping redundant orders
         
         
        if(result != -1 or master_context[TYPE][ACT]!=[]):    
            result    = -1
            result    = strategy_run.hedge_live_orders(TYPE,'sell') 
            
        return(result)
    
    def directional_put(self,context,lot_size,coin): # buy options
        global master_config
        global CE
        global PE
        global CEM
        global PEM	
        
        global ORDER_SCRIP #0
        global SPOT_PRICE #0
        global CE_SCRIP #1
        global PE_SCRIP #2
        global CE_ATM   #3
        global PE_ATM   #4
        global log
        global delta
        global accounts
        global trade_context
        global master_context

        STATUS      = 0
        TOL         = 1
        SL_TOL      = 2
        SPOT_TOL    = 3
        response1   = []
        PE_DIR      = -1
        #log.info("AM-3010")
        exp = next_expiry()
        search_str = master_config[PE][COIN]
        result = strategy_run.status_check('P',exp)  # 0 if active order is Null
        if(master_config[TYPE][STATUS] == 0 and result != -1):
            master_context[TYPE][CTX] = trade_context[:]
            master_context[TYPE][CTX][CE_SCRIP] = master_context[TYPE][CTX][PE_SCRIP] # store new pe scrip & value in arr[2] and arr[3] respectively
            master_config[TYPE][STATUS]  = 1
        
        elif(master_config[TYPE][STATUS] == 1):
            master_context[TYPE][CTX][CE_SCRIP] = master_context[TYPE][CTX][PE_SCRIP] # store new pe scrip & value in arr[2] and arr[3] respectively
            master_context[TYPE][CTX][CE_ATM]   = delta.get_current_value(master_context[TYPE][CTX][CE_SCRIP]) # reuse for new ltp for pe

            # pe,tol,prem hike,buy
            #response1 = strategy_run.place_dir_orders(PE_DIR,master_config[TYPE][SPOT_TOL],master_config[TYPE][TOL],'buy',coin,lot_size) 
            #response1 = strategy_run.place_dir_orders(PE_DIR,master_config[TYPE],'buy',master_config[SHEET][COIN],lot_size) 
            
        result = accounts.get_order_history()
        if(result != -1):
            master_context[TYPE][ACT] = result[:] 
            
        response2    = []
        response2    = strategy_run.hedge_live_orders("sell",master_config[TYPE][SL_TOL]) # SL tolerance
            
        if(response1 != []):
            master_config[TYPE][TOL]     = float(0.75*master_config[TYPE][TOL])
            master_config[TYPE][SL_TOL]  = float(0.75*master_config[TYPE][SL_TOL])

            result      = context.update_orders(TYPE)
            #master_context[TYPE][CTX] = trade_context
        out = accounts.get_live_orders()
        if(out != -1):
            master_context[TYPE][PAS] = out[:] 
        return(response1)

    def duplicate_non_directional(self,context,lot_size,coin):
        response1 = 1
        response = strategy_run.long_strangle(self,context)
        #response1 = strategy_run.directional_call(self,context) # buy options
        #response2 = strategy_run.directional_put(self,context,lot_size,master_config[SHEET][COIN]) # buy options
        #if(response1 != -1 and response2 != -1):
        #    return(0)
        return (0)#return(-1) 
    

    ###################################################################################################
    # place_dir_orders(context type(arguments: 1<=integer <=4),buysell ('buy' or 'sell'))
    # if ITM order exists,add one more .else place a new ATM order
    # update the context 
    ###################################################################################################
    @classmethod
    def place_dir_orders(self,ctx_type,buysell): # CE 1 ,PE 2 CEM 3 PEM 4 
        global ACT	
        global PAS	
        global master_context
        global master_config 
        global context
        global ORDER_LTP

        TYPE        = ctx_type

        LIVE        = 0
        SCRIP       = 0
        SHEET       = 0
        LOT         = 8
        NEW_ATM     = 1
        OLD_ATM     = 2
        TOL         = 1
        SPOT_PRICE  = 0 
        lot_size    = master_config[SHEET][LOT]
        order_flag  = 0
        active_flag = 0
        order_ctx   = master_context[TYPE][LIVE]
        if(master_context[TYPE][ACT] != []):
            active_flag = 1
        
        result = 0
        dir_sign = -1
        for i in range(TYPE): #1:1 ,2:1,3:-1,4:1
            dir_sign = dir_sign * -1

        if(float(order_ctx[NEW_ATM])>=(1+master_config[TYPE][TOL])*float(order_ctx[OLD_ATM])): # 1.2 * local_c
            print(f" spot {str(master_context[SHEET][SPOT_PRICE])} order {str(order_ctx[NEW_ATM])} tol {str(master_config[TYPE][TOL])}")
            #print(total_orders)
            if(active_flag == 0 and (dir_sign*(master_context[SHEET][SPOT_PRICE] - float(order_ctx[NEW_ATM]))>=float(master_config[TYPE][TOL]))):
                pid = 0
                val = 0
                pid = delta.get_product_id(master_context[TYPE][LIVE][SCRIP])        # ce scrip
                val = float(order_ctx[NEW_ATM])
                if(pid !=0 and val != 0):
                    response = []
                    #response = deltaorder.market_order(pid,lot_size,buysell)             # buy order
                    if(response != []):
                        beep(1)
                        order_flag = 1
                        print("order {master_context[TYPE][LIVE][SCRIP]} spot changed from {order_ctx[NEW_ATM]} to {master_context[SHEET][SPOT_PRICE]} ")
                
            elif(active_flag != 0):
                scrip_str = ''
                #print("buy at ATM or add one lot to the existing buy order,whichever is lower")
                for order in master_context[TYPE][ACT]:
                    strike = float(order[SCRIP].split('-')[2])                            # strike price of active order
                    if(dir_sign* (float(master_context[SHEET][SPOT_PRICE]) - strike) >0):
                        scrip_str = order[SCRIP]  # scrip for existing order
                    else:
                        scrip_str = order_ctx[SCRIP]       # ATM
                if(scrip_str != ''):
                    pid = 0
                    val = 0
                    pid = delta.get_product_id(scrip_str)        # ce scrip
                    val = delta.get_current_value(scrip_str)

                    if(pid != 0 and val != 0):
                        print("add "+ buysell+" " +str(lot_size)+ " lot of " + scrip_str + " for " + str(val))
                        response = []
                        #response = deltaorder.market_order(pid,lot_size,buysell) # buy order
                        if(response != [] ):
                            beep(1)
                            order_flag = 1
                            print("add {master_context[TYPE][LIVE][SCRIP]} spot changed from {order_ctx[NEW_ATM]} to {master_context[SHEET][SPOT_PRICE]} ")
                
                    else:
                        print(f"pid {pid} or value {val} is 0 for {scrip_str}")
            if(order_flag == 1):
                result = accounts.get_order_history()
                if(result != -1):
                    result  = -1
                    result  = context.update_orders(TYPE)
                    if(result != -1):
                        for order in master_context[TYPE][ACT]: # format ['C-BTC-34750-120522', 1, -1.0]
                            ltp    = float(delta.get_current_value(order[SCRIP]))                        # update LTP
                            if(ltp == -1):
                                print("Update ltp for active order "+order[SCRIP]+ "failed")
                                log.error("AM-4014-"+order[SCRIP])
                                return(-1)
                            order[ORDER_LTP] = ltp

                    else:
                        print(f"Update context failed for type {TYPE}") #1 CE, 2 PE ,3 CEM, 4 PEM
                else:
                    print(f"active order update, after placing order, failed")
                    result = -1
            elif(active_flag == 0):
                result  = context.update_context(TYPE)
        return(result)
        

    def directional_call(self,context): # buy options
        global master_config
        global master_context
        global CE 
        global ACT
        global PAS
        LIVE    = 0
        SCRIP   = 0
        NEW_ATM = 1
        OLD_ATM   = 2
        global ORDER_LTP   #2
        global ORDER_SCRIP #0

        global SPOT_PRICE #0
        global log
        global delta
        #global trade_context

        TYPE        = 1 #CE 
        STATUS      = 0
        TOL         = 1
        SL_TOL      = 2
        SPOT_TOL    = 3
        #CE_DIR      = 1
        #response1   = []
        log.info("AM-3010")
        exp = next_expiry()
        search_str = master_config[TYPE][COIN]
        
        if(master_context[TYPE][ACT]!=[]):
            # Update LTP for active orders
            for order in master_context[TYPE][ACT]: # format ['C-BTC-34750-120522', 1, -1.0]
                ltp    = float(delta.get_current_value(order[SCRIP]))                        # LTP
                if(ltp == -1):
                    print("Update ltp for active order "+order[SCRIP]+ "failed")
                    log.error("AM-4014-"+order[SCRIP])
                    return(-1)
                pl = (float(order[ORDER_LTP])-ltp)/float(order[ORDER_LTP])   # PL percentage
                if(pl < 0.0 or pl< master_config[TYPE][SL_TOL]): #check if order is in profit or within SL range
                    master_config[TYPE][STATUS]  = 1
                
                order[ORDER_LTP] = ltp 

        # check for stale passive orders and delete them
        result = strategy_run.status_check(TYPE)  # pass CE as 1 , returns 0 if active order is Null
        if(result != 0):
            print("Could not delete weekly stale passive orders..Order list : {master_context[CE][PAS]}")
            return(-1)
        if(master_config[TYPE][STATUS] == 0 and result == 0):
            master_config[TYPE][STATUS]  = 1
        
        elif(master_config[TYPE][STATUS] == 1):
            master_context[TYPE][LIVE][OLD_ATM] = master_context[TYPE][LIVE][NEW_ATM] # store new ce scrip & val in arr[2] and arr[3] resp
            master_context[TYPE][LIVE][NEW_ATM] = delta.get_current_value(master_context[TYPE][LIVE][SCRIP]) # reuse for new ltp for ce

            result = strategy_run.place_dir_orders(TYPE,'buy') 
            master_context[TYPE][LIVE][OLD_ATM] = master_context[TYPE][LIVE][NEW_ATM] # update old ltp to avoid looping redundant orders
         
         
        if(result != -1 or master_context[TYPE][ACT]!=[]):    
            result    = -1
            result    = strategy_run.hedge_live_orders(TYPE,'sell') 
            
        return(result)
    
    def directional_put(self,context,lot_size,coin): # buy options
        global master_config
        global CE
        global PE
        global CEM
        global PEM	
        
        global ORDER_SCRIP #0
        global SPOT_PRICE #0
        global CE_SCRIP #1
        global PE_SCRIP #2
        global CE_ATM   #3
        global PE_ATM   #4
        global log
        global delta
        global accounts
        global trade_context
        global master_context

        STATUS      = 0
        TOL         = 1
        SL_TOL      = 2
        SPOT_TOL    = 3
        response1   = []
        PE_DIR      = -1
        #log.info("AM-3010")
        exp = next_expiry()
        search_str = master_config[PE][COIN]
        result = strategy_run.status_check('P',exp)  # 0 if active order is Null
        if(master_config[TYPE][STATUS] == 0 and result != -1):
            master_context[TYPE][CTX] = trade_context[:]
            master_context[TYPE][CTX][CE_SCRIP] = master_context[TYPE][CTX][PE_SCRIP] # store new pe scrip & value in arr[2] and arr[3] respectively
            master_config[TYPE][STATUS]  = 1
        
        elif(master_config[TYPE][STATUS] == 1):
            master_context[TYPE][CTX][CE_SCRIP] = master_context[TYPE][CTX][PE_SCRIP] # store new pe scrip & value in arr[2] and arr[3] respectively
            master_context[TYPE][CTX][CE_ATM]   = delta.get_current_value(master_context[TYPE][CTX][CE_SCRIP]) # reuse for new ltp for pe

            # pe,tol,prem hike,buy
            #response1 = strategy_run.place_dir_orders(PE_DIR,master_config[TYPE][SPOT_TOL],master_config[TYPE][TOL],'buy',coin,lot_size) 
            #response1 = strategy_run.place_dir_orders(PE_DIR,master_config[TYPE],'buy',master_config[SHEET][COIN],lot_size) 
            
        result = accounts.get_order_history()
        if(result != -1):
            master_context[TYPE][ACT] = result[:] 
            
        response2    = []
        response2    = strategy_run.hedge_live_orders("sell",master_config[TYPE][SL_TOL]) # SL tolerance
            
        if(response1 != []):
            master_config[TYPE][TOL]     = float(0.75*master_config[TYPE][TOL])
            master_config[TYPE][SL_TOL]  = float(0.75*master_config[TYPE][SL_TOL])

            result      = context.update_orders(TYPE)
            #master_context[TYPE][CTX] = trade_context
        out = accounts.get_live_orders()
        if(out != -1):
            master_context[TYPE][PAS] = out[:] 
        return(response1)

    def non_directional(self,context,lot_size,coin):
        response1 = 1
        response = strategy_run.long_strangle(self)
        #response1 = strategy_run.directional_call(self,context) # buy options
        #response2 = strategy_run.directional_put(self,context,lot_size,master_config[SHEET][COIN]) # buy options
        #if(response1 != -1 and response2 != -1):
        #    return(0)
        return (0)#return(-1)


    def lstrad_sstran(self,context):
        global master_context
        global master_config
        global log
        global deltaorder
        global util
        global breakeven
        global seperator
        global SL_TOL
        global LIVE
        global ORDER_SCRIP
        global TOL
        global LAST_SL
        global BUY
        global SELL
        global delete_context
        global log
        global buy_enabled
        global sell_enabled
        
        local_log = ""
        buy  = 0
        sell = 0
        
        for i in range(1,max_type+1): #Daily CE and PE Alone 
            TYPE = i
            master_config[TYPE][SL_TOL] = 0.2 # Set higher stop loss for this strategy
            if(TYPE == 1):
                direction = 1
            elif(TYPE == 2):
                direction = -1

            
            if(master_context[TYPE][ACT] == []):
                ###########create cancel list #####################
                sell_order = 0
                cancel_list = []
                for order in master_context[TYPE][PAS]:
                    if(int(order[ORDER_LOT])<0):
                        sell_order = 1
                    elif(int(order[ORDER_LOT])>0):
                        if(cancel_list != []):
                            cancel_list.append(order)
                        else:
                            cancel_list.insert(0,order)
                

                if(sell_order ==0 and sell_enabled == 1):
                    out = util.check_premium_expiry(TYPE)
                    if(out == -1):# cancel all pending orders and change the expiry dates
                        ################### update expiry date and context ###################
                        #for order in cancel_list:
                        #    master_context[TYPE][PAS].remove(order)
                        master_context[TYPE][PAS] = [p_order for p_order in master_context[TYPE][PAS] if(p_order != order)]
                        master_config[TYPE][EXPIRY]  =  gettimer.second_next_expiry()
                        print(f"Expiry date changed to next day i.e, {master_config[TYPE][EXPIRY]}\n")
            
            result = account_context.validate_atm(TYPE)
            if(result == -1):
                print(f"validate for type {TYPE} failed")
                return(-1)

                    
            ###################### check for new order placement
            hedge   = 1
            out     = util.decider(TYPE,hedge)
            if(out != -1 or out != []):
                buy  = int(out[0])
                sell = int(out[1])
                local_log = local_log + out[2]
            ##################### place sell orders ########################
            if(sell >0 and sell_enabled == 1):
                scrip   = 0
                scrip   = master_context[TYPE][LAST_SL][SELL][ORDER_SCRIP]
                val     = 0
                if(scrip != 0):
                    val = float(delta.get_current_value(scrip))
                
                if(val <= 0 or (val > 0 and val < master_context[TYPE][LAST_SL][SELL][VALUE])):
                    factor  = -1
                    ctx     = master_context[TYPE][LIVE][ORDER_SCRIP].split(seperator)
                    ctx[2]  = str(int(ctx[2]) + direction*breakeven)
                    scrip = seperator.join(ctx)
                    print(f"\n scrip {scrip}, val {val} last_sl {master_context[TYPE][LAST_SL][SELL][ORDER_SCRIP]} ")
                    #master_context[TYPE][LAST_SL][SELL][ORDER_SCRIP] = seperator.join(ctx)
                    out1 = 0
                    out1 = util.limit_order_create('sell',scrip,TYPE,factor,sell,TOL);
                    if(out1 != 0 and out1[0] != -1):
                        local_log = local_log + out1[1] +'\n'
            
            #################### place buy orders  ##########################
            if(buy > 0 and buy_enabled == 1):
                factor  = 1
                val = master_config[TYPE][TOL]
                master_config[TYPE][TOL] = 0.1 # Set low tolerance for this strategy
                if(master_context[TYPE][LAST_SL][BUY][ORDER_SCRIP] == 0):
                    master_context[TYPE][LAST_SL][BUY][VALUE]   = 0
                    master_context[TYPE][LAST_SL][BUY][ORDER_SCRIP]   = master_context[TYPE][LIVE][ORDER_SCRIP]
                out2 = 0
                out2 = util.limit_order_create('buy',master_context[TYPE][LAST_SL][BUY][ORDER_SCRIP],TYPE,factor,buy,TOL);
                if(out2 != 0 and out2[0] != -1):
                    local_log = local_log + out2[1] +'\n'
                master_config[TYPE][TOL] = val 
            ###################################################################

        delete_context = []
        delete_context.append(master_context[1][ACT])
        delete_context.append(master_context[1][PAS])
        delete_context.append(master_context[2][ACT])
        delete_context.append(master_context[2][PAS])
        log.info(local_log)
        local_log = ''
        return(1)


        # check for existing orders
        # if there is no order,
        #   check conditions for reorder and place accordingly
        #   place limit orders for long straddle and short strangle
        # if orders exist ,check the following cases
        # 1. if all orders are positive 
        # 2. if buy order is positive
        # 3. if buy order is negative
        # 4. if sell order is postive
        # 5. if sell orrder is negative
        # 6. if all orders are negative
        # 7. no movement or range bound
        # 8. if direction reverses
        # 9. if the movement is zigzag
        #10. one way move
        #11. make sure all exis options are considered

        # make sure 
        # no buy order is beyond sell mark price(for both active and passive)
        # close sell if no active buy is available and strike is breached (or) buy closer to atm and sell opposite side <-- check this 
        # if passive close mark price is breached, close the sell and place a sell 'tolerance' points away
        #1. All active orders are hedged ,in sell case, hedged with an active or passive buy order
        #2. no active and passive stale orders are present
    
    def iron_fly(self,context):
        global master_context
        global master_config
        global log
        global deltaorder
        global util
        global breakeven
        global seperator
        global SL_TOL
        global LIVE
        global ORDER_SCRIP
        global TOL
        global LAST_SL
        global BUY
        global SELL
        global delete_context
        global log
        global buy_enabled
        global sell_enabled
        
        local_log = ""
        buy  = 0
        sell = 0
        
        for i in range(1,max_type+1): #Daily CE and PE Alone 
            TYPE = i
            master_config[TYPE][SL_TOL] = 0.2 # Set higher stop loss for this strategy
            if(TYPE == 1):
                direction = 1
            elif(TYPE == 2):
                direction = -1

            
            if(master_context[TYPE][ACT] == []):
                ###########create cancel list #####################
                sell_order = 0
                #cancel_list = []
                #for order in master_context[TYPE][PAS]:
                #    if(int(order[ORDER_LOT])<0):
                #        sell_order = 1
                #    elif(int(order[ORDER_LOT])>0):
                #        if(cancel_list != []):
                #            cancel_list.append(order)
                #        else:
                #            cancel_list.insert(0,order)
                

                if(sell_order ==0 and sell_enabled == 1):
                    out = util.check_premium_expiry(TYPE)
                    if(out == -1):# cancel all pending orders and change the expiry dates
                        ################### update expiry date and context ###################
                        #for order in cancel_list:
                        #    master_context[TYPE][PAS].remove(order)
                        master_context[TYPE][PAS] = [p_order for p_order in master_context[TYPE][PAS] if(p_order != order)]
                        master_config[TYPE][EXPIRY]  =  gettimer.second_next_expiry()
                        print(f"Expiry date changed to next day i.e, {master_config[TYPE][EXPIRY]}\n")
            
            result = account_context.validate_atm(TYPE)
            if(result == -1):
                print(f"validate for type {TYPE} failed")
                return(-1)

                    
            ###################### check for new order placement
            hedge   = 0
            out     = util.decider(TYPE,hedge)
            if(out != -1 or out != []):
                buy  = int(out[0])
                sell = int(out[1])
                local_log = local_log + out[2]
            ##################### place sell orders ########################
            if(sell >0 and sell_enabled == 1):
                scrip   = 0
                scrip   = master_context[TYPE][LAST_SL][SELL][ORDER_SCRIP]
                val     = 0
                if(scrip != 0):
                    val = float(delta.get_current_value(scrip))
                
                if(val <= 0 or (val > 0 and val < master_context[TYPE][LAST_SL][SELL][VALUE])):
                    factor  = -1
                    ctx     = master_context[TYPE][LIVE][ORDER_SCRIP].split(seperator)
                    ctx[2]  = str(int(ctx[2]) + direction*breakeven)
                    scrip = seperator.join(ctx)
                    print(f"\n scrip {scrip}, val {val} last_sl {master_context[TYPE][LAST_SL][SELL][ORDER_SCRIP]} ")
                    #master_context[TYPE][LAST_SL][SELL][ORDER_SCRIP] = seperator.join(ctx)
                    out1 = 0
                    out1 = util.limit_order_create('sell',scrip,TYPE,factor,sell,TOL);
                    if(out1 != 0 and out1[0] != -1):
                        local_log = local_log + out1[1] +'\n'
            
            #################### place buy orders  ##########################
            if(buy > 0 and buy_enabled == 1):
                factor  = 1
                val = master_config[TYPE][TOL]
                master_config[TYPE][TOL] = 0.1 # Set low tolerance for this strategy
                if(master_context[TYPE][LAST_SL][BUY][ORDER_SCRIP] == 0):
                    master_context[TYPE][LAST_SL][BUY][VALUE]   = 0
                    master_context[TYPE][LAST_SL][BUY][ORDER_SCRIP]   = master_context[TYPE][LIVE][ORDER_SCRIP]
                out2 = 0
                out2 = util.limit_order_create('buy',master_context[TYPE][LAST_SL][BUY][ORDER_SCRIP],TYPE,factor,buy,TOL);
                if(out2 != 0 and out2[0] != -1):
                    local_log = local_log + out2[1] +'\n'
                master_config[TYPE][TOL] = val 
            ###################################################################

        delete_context = []
        delete_context.append(master_context[1][ACT])
        delete_context.append(master_context[1][PAS])
        delete_context.append(master_context[2][ACT])
        delete_context.append(master_context[2][PAS])
        log.info(local_log)
        local_log = ''
        return(1)
        
    def long_strangle (self):
        global deltaorder
        global delta
        global master_context
        global master_config
        global ORDER_SCRIP
        global ORDER_PID
        global ORDER_TRIG #3
        global ORDER_ID
        global ORDER_LTP  #2
        global CE
        global PE
        global ACT
        global PAS
        global seperator
        global accounts
        global order_status_change
        #ACTIVE_LTP   = 3
        #AORDER_PID   = 3
        sl_counted  = 0
        ref_order   = 0
        gap         = 500 # place ITM 500 points orders
        target      = 210 # target in percentage
        for TYPE in range(1,max_type+1): #Daily CE and PE Alone
            sl_counted = 0
            out = util.check_expiry(TYPE)

            #print(f"ACT is {master_context[TYPE][ACT]}")
            hedge       = 0
            hedge_count = 100 # to differtiate between zero sell and balanced sell 
            place_new_order = 1
            PAIR    = (TYPE%2+1) + int((TYPE-1)/2)*2
            for a_order in master_context[TYPE][ACT]:
                a_order[ORDER_LTP] = float(delta.get_current_value(a_order[ORDER_SCRIP]))
                if(a_order[ORDER_LOT]>0):
                    place_new_order  = 0
                    hedge = a_order
                    hedge[ORDER_LTP]    = float(hedge[ORDER_LTP])
                    hedge[ORDER_TRIG]   = float(hedge[ORDER_TRIG])
                elif(a_order[ORDER_LOT]<0): # add more checks to ensure ,this the SL order
                    sl_counted = sl_counted + abs(a_order[ORDER_LOT])
                    if(hedge_count ==100):
                        hedge_count = 0
                    hedge_count= hedge_count - abs(a_order[ORDER_LOT])
            
            for p_order in master_context[TYPE][PAS]:
                p_order[ORDER_LTP] = float(delta.get_current_value(p_order[ORDER_SCRIP]))
                p_order[ORDER_TRIG]= float(p_order[ORDER_TRIG])
                cancel_existing_order = 0
                place_new_order  = 0
                
                if(p_order[ORDER_LOT]>0):
                    for pair_order in master_context[PAIR][ACT]:
                        if(pair_order[ORDER_LOT]>0): 
                            place_new_order = 0
                            pair_order[ORDER_LTP] = float(delta.get_current_value(pair_order[ORDER_SCRIP]))
                            if(abs(float(pair_order[ORDER_TRIG])-pair_order[ORDER_LTP])<=4):
                                cancel_existing_order = 1   
                    if(p_order[ORDER_LTP]<(float(p_order[ORDER_TRIG])/1.5)-30):
                        cancel_existing_order = 2
                    #for pair_order in master_context[PAIR][PAS]:
                    #    if(pair_order[ORDER_LOT]>0):
                    #        #print(f"\npair {master_context[PAIR][PAS]}")
                    #        #print(f"\npassive {master_context[TYPE][PAS]}")
                    #        pair_order[ORDER_LTP]   = float(pair_order[ORDER_LTP])
                    #        pair_order[ORDER_TRIG]  = float(pair_order[ORDER_TRIG])
                    #        p_order[ORDER_TRIG]     = float(p_order[ORDER_TRIG])
                    #        pair_trig   = (pair_order[ORDER_TRIG]/1.5)#-10 
                    #        p_trig      = (p_order[ORDER_TRIG]/1.5)#-10
                    #        #print(f"\npair:ltp {pair_order[ORDER_LTP]} trig {pair_trig} pas :ltp {p_order[ORDER_LTP]} trig {p_trig}")
                    #        if(pair_order[ORDER_LTP]< pair_trig and p_order[ORDER_LTP]<p_trig):
                    #            response= deltaorder.cancel(pair_order[ORDER_PID],pair_order[ORDER_ID])
                    #            if(response != -1):
                    #                master_context[PAIR][PAS] = [ordr for ordr in master_context[PAIR][PAS] if(ordr != pair_order)]
                    #                response = util.place_suitable_order (PAIR,gap,'buy')
                    #                cancel_existing_order = 1

                    if(cancel_existing_order ==0):
                        place_new_order = 0

                elif(p_order[ORDER_LOT]<0): # Target and SL orders for the open Active order
                    if(hedge ==0): # no active order.so clear all hedge orders
                        cancel_existing_order = 3
                    #elif(p_order[ORDER_SCRIP] == hedge[ORDER_SCRIP]):
                    else:
                        if(hedge_count == 100):
                            hedge_count = 0
                        if(p_order[ORDER_TRIG]< hedge[ORDER_TRIG]): #and sl_counted == 0):      # SL order
                            #if(hedge_count != 1):
                            hedge_count = hedge_count -abs(p_order[ORDER_LOT])
                            #sl_counted  = 1
                            sl_counted = sl_counted + abs(p_order[ORDER_LOT])
                            trig = hedge[ORDER_TRIG]
                            lot  = 1*int(master_config[SHEET][LOT])
                            if(hedge[ORDER_LTP] > trig and p_order[ORDER_TRIG]< trig and p_order[ORDER_LOT] == lot):
                                if((hedge[ORDER_LTP] - p_order[ORDER_TRIG])> (hedge[ORDER_TRIG]/2)+10):
                                    cancel_existing_order = 4
                                    #if(hedge_count != 1):
                                    hedge_count = hedge_count + abs(p_order[ORDER_LOT])         # To compensate
                        elif(p_order[ORDER_TRIG]> hedge[ORDER_TRIG]):    # Target Order
                            hedge_count = hedge_count + abs(p_order[ORDER_LOT])

                if(cancel_existing_order != 0):
                    if(order_status_change == 0):
                        print('\n')
                    order_status_change = 1
                    response= deltaorder.cancel(p_order[ORDER_PID],p_order[ORDER_ID])
                    if(response == -1):
                        place_new_order  = 0
                        print(f"cancel of order {p_order[ORDER_SCRIP]} failed")
                    elif(response != -1):
                        print(f"Cancelled order {p_order} due to {cancel_existing_order} new order status {place_new_order}")
                        master_context[TYPE][PAS] = [x_order for x_order in master_context[TYPE][PAS] if(x_order != p_order)]
                        if(cancel_existing_order == 2 or cancel_existing_order ==4):
                            ref_order = p_order
                            print(f"replace cancelled order for {TYPE}")
                            response = util.place_suitable_order (TYPE,gap,'sell',ref_order)
                            cancel_existing_order = 0
            
            #if(sl_counted == 2 and hedge_count == 0):
            #    hedge = 0

            if(place_new_order != 0):
                if(order_status_change == 0):
                    print('\n')
                order_status_change = 1
                print(f"place order for {TYPE}")
                response = util.place_suitable_order (TYPE,gap,'buy',ref_order)
            ###############################################################################
            ######################### HEDGE ACTIVE ORDERS #################################
            ###############################################################################
        if(hedge != 0):
            strategy_run.hedge_active_orders(self,hedge,sl_counted,order_status_change,TYPE,hedge_count)
            hedge = 0
    
    def hedge_active_orders(self,hedge,sl_counted,order_status_change,TYPE,hedge_count):
        global master_context
        global master_config
        global ORDER_SCRIP
        global ORDER_PID
        global ORDER_ID
        global ORDER_LTP
        global ORDER_LOT
        global ORDER_TRIG
        global SHEET
        global LOT
        
        global accounts
        global util
        global delta
        target      = 210 # target in percentage
        
        hedge_type = 3

        if(hedge != 0):

            if(order_status_change == 0 and sl_counted < hedge_type*int(master_config[SHEET][LOT])):
                print(f'sl count {sl_counted} \n')
            #print(f"hedge order is non zero {hedge}")
            order_status_change = 1
            if(float(hedge[ORDER_LTP]) < float(hedge[ORDER_TRIG])): # order in loss
                val     = float(hedge[ORDER_TRIG])
            else:
                val     = float(hedge[ORDER_LTP])
            #if(hedge_count == 1 or hedge_count == 100): # place stoploss order
            if(sl_counted ==0 or sl_counted<hedge_type):#if(sl_counted%2 ==0): # place 50% sl order
                response = 0
                sell_pid= util.closest_order(hedge[ORDER_SCRIP],-50,TYPE)[1] #[scrip,pid]
                if(sell_pid == -1):
                    print("Could not find closest order")
                    return(0)#continue

                if(sl_counted == 0 or sl_counted == 2*int(master_config[SHEET][LOT])):
                    #response= deltaorder.stoploss_limit(hedge[ORDER_PID],hedge[ORDER_LOT],'sell',float(val/2)-10,(val/2),val)
                    response= deltaorder.stoploss_limit(sell_pid,hedge[ORDER_LOT],'sell',float(val/2)-10,(val/2),val)
                
                    if(response == -1):
                        print(f"stoploss order for {hedge[ORDER_SCRIP]} failed!")
                        response= deltaorder.stoploss_limit(sell_pid,hedge[ORDER_LOT]*4,'sell',float(val/4)-10,(val/4),val)
                        if(response != -1):
                            accounts.parse_passive_orders(response,TYPE)
                            sl_counted = sl_counted + int(hedge[ORDER_LOT])*4

                    else:
                        print(f"stoploss order for {hedge[ORDER_SCRIP]} placed")
                        accounts.parse_passive_orders(response,TYPE)
                        sl_counted = sl_counted + int(hedge[ORDER_LOT])
                
            if(sl_counted == 1*int(master_config[SHEET][LOT])):
                sell_pid= util.closest_order(hedge[ORDER_SCRIP],-50,TYPE)[1] #[scrip,pid]
                if(sell_pid == -1):
                    print("Could not find closest order")
                    return(0) #continue
                response = -1
                response= deltaorder.stoploss_limit(sell_pid,hedge[ORDER_LOT]*2,'sell',float(val/4)-10,(val/4),val)
                if(response != -1):
                    print(f"25% stoploss order for {hedge[ORDER_SCRIP]} placed")
                    accounts.parse_passive_orders(response,TYPE)

            if((hedge_count == sl_counted*-1)or hedge_count == 100):# place Target order
                response = 0
                response= deltaorder.place_order(str(hedge[ORDER_PID]),str(hedge[ORDER_LOT]),'sell',str(float(val*target/100)))
                if(response == -1):
                    print(f"Target order for {hedge[ORDER_SCRIP]} failed!")
                else:
                    accounts.parse_passive_orders(response,TYPE)
                    print(f"Target order for {hedge[ORDER_SCRIP]} placed")


            #hedge = 0
            ################################################################################


    def buy_and_adjust(self):
            global master_context
            global master_config
            global ORDER_SCRIP
            global ORDER_PID
            global ORDER_ID
            global ORDER_LTP
            

            global CE
            global PE
            global SL_TOL
            
            global delta

            ACTIVE_LTP  = 4
            loss        = 0
            loss_percent= 0.0

            gains = util.expiry_gains()
            for TYPE in range(1,max_type+1): #Daily CE and PE Alone
                PAIR    = (TYPE%2+1) + int((TYPE-1)/2)*2
                master_config[TYPE][SL_TOL] = 0.2 # Set higher stop loss for this strategy
                count = [0,0,0,0] # a_buy,p_buy,a_Sell,p_sell
                for a_order,p_order in zip(master_context[TYPE][ACT],master_context[TYPE][PAS]):
                    index = 0 if(a_order[ORDER_LTP]>0 or p_order[ORDER_LTP]>0) else 2
                    count[index] = a_order
                    
                    if(count[index]!=0): #delete this order as there is an active order already
                        response = deltaorder.cancel(p_order[ORDER_PID],p_order[ORDER_ID]) 
                        if(response == -1):
                            print(f"cancel order for {p_order} failed.Active order {count[0]} present already")
                        elif(response != -1):
                            master_context[TYPE][PAS] = [x_order for x_order in master_context[TYPE][PAS] if(x_order != p_order)]
                            p_order = 0 # check if this is required
                    else:
                        count[index+1] = p_order
                # Three basic cases from now
                # 1. no order --> place order
                # 2. Order is in profit --> No nothing .later add logic to safegaurd gained profit
                # 3. order is in loss --> Add or modify adjustments.close order if required

                # case 1: no order found.place new order
                #if(count[0] == 0 and count[1] == 0): # no buy order,place a new one
                    # if tolerance is met, place ATM orders instead of ITM
                    #response = util.limit_order_create('buy',master_context[TYPE][LIVE][ORDER_SCRIP],TYPE,factor,buy,TOL)
                    
                if(count[0] !=0): # Active order is present
                    a_order     = count[0]
                    loss        = float(a_order[ORDER_LTP]) - float(a_order[ACTIVE_LTP])
                    loss_percent= loss*100/float(a_order[ORDER_LTP])

                # case 2: Order is in profit.Do nothing for now.In future ,if target is hit,add a pair buy to safegaurd the profit
                if(loss<0):
                    continue

                # case 3: Order is in loss. Add or modify hedge
                if(loss_percent > 10.0):
                    if(count[2] == 0):
                        loss = loss *2

                    elif(count[2] != 0):
                        a_order     = count[2]
                        if(loss > (int(float(a_order[ORDER_LTP])/10)+1)):
                            # for every 10% loss ,close the existing sell and place a new sell order close to the buy ltp
                            response = deltaorder.market_order(a_order[ORDER_PID],abs(order[SIZE]),'buy')
                        else:
                            loss = 0 # just to avoid placing sell order below
                        
                    if(loss !=0):
                        response = -1
                        response = util.place_suitable_order(TYPE,loss,'sell',0)
                    
                    # stop loss at 50% .Keep the sell order for compensation
                    if(loss_percent > 50.0):
                        response = deltaorder.market_order(order[0][ORDER_PID],abs(order[SIZE]),'sell')
                        


                #if(gains[0]<0):
                #    if(count[0] != 0 and loss >0): # buy in loss 
                #        order = [0,0] # [scrip, pid]
                #        order = util.find_suitable_order(TYPE,(loss*2))
                #        if(order[1] != 0):
                #            response == 0
                #            response = deltaorder.market_order(order[1],abs(order[SIZE]),'sell')
                #            if(response == -1):
                #                print(f"Market order for {order[0]} failed")
                ## Touch the sell orders onl if they becomes ITM
                #if(count[2] != 0): 
                #    if(gains[0] <0 and gains[TYPE]==-1): # sell order is in loss and is ITM
                #        response == 0
                #        response = deltaorder.market_order(count[2][ORDER_PID],abs(order[SIZE]),'buy')
                #        if(response == -1):
                #            print(f"Market order for {count[2][ORDER_SCRIP]} buy failed")
                #    elif(gains[TYPE] != -1 and loss<0):
                        

                

                
            # set target and stoploss # target 50% loss 0 for buy order,dont care if buy < sell,otherwise  sL = atm for sell order
            # Sell PE sell CE buy PE buy CE
            #  0        0       0       0 => if PAS == null ,buy CE limit and PE limit,else buy as required
            #  0        0       0       1 => for this and below,if in profit,if target not hit,dont care
            #  0        0       1       0 => else place an Market SL 2x the current loss for every 10% net loss
            #  0        0       1       1 => sell to hedge the losing side 
            #  1        0       0       0 => DC if in profit, sl = ATM if in losses,buy CE limit and PE limit as required
            #  1        0       0       1 => only for this, adjust PE buy limit.for this and below,if in profit,if target not hit,dont care
            #  1        0       1       0 => else place an Market SL 2x the current loss for every 10% net loss
            #  1        0       1       1 => sell to hedge the losing side
            

class account_context:

    def __init__(self,coin,expiry):
        self.delta  = delta
        log.info("AM-4000-"+coin+"-"+expiry)
    
    #def validate_atm(scrip,val,expiry,coin,sym):
    def validate_atm (ctx_val):
        global master_config
        global CE
        global PE
        global CEM
        global PEM	

        TYPE        = ctx_val
        LIVE        = 0
        CTX_SCRIP   = 0
        SHEET       = 0
        SCRIP       = 1
        COIN        = 4
        EXPIRY      = 5
        multiplier  = 50
        factor      = (TYPE )%2 # 0 for PE and 1 for CE
        OLD_LTP     = 2
        NEW_LTP     = 1
        SPOT_LTP    = 0
        COINNAME    = 0
        
        global trade_context
        global delta
        global log

        LTP     = 0
        #print(f"sheet is {master_config[SHEET]}")
        master_context[SHEET][SPOT_LTP]    = float(delta.get_current_value(master_config[SHEET][COINNAME]+"USDT"))      # spot  price
        value       = master_context[SHEET][SPOT_LTP]
        master_context[TYPE][LIVE][CTX_SCRIP]    = master_config[TYPE][COIN]+"-"+str((int(value/multiplier)+factor)*multiplier)+"-"+master_config[TYPE][EXPIRY]

        val = -1	
        val = delta.get_current_value(master_context[TYPE][LIVE][CTX_SCRIP])            # ATM val
        if(val == -1):
            for i in range(1,10):
                multiplier = i *50
                master_context[TYPE][LIVE][CTX_SCRIP]    = master_config[TYPE][COIN]+"-"+str((int(value/multiplier)+factor)*multiplier)+"-"+master_config[TYPE][EXPIRY]
                val      = delta.get_current_value(master_context[TYPE][LIVE][CTX_SCRIP])
                if(val != -1):
                    master_context[TYPE][LIVE][OLD_LTP] = float(master_context[TYPE][LIVE][NEW_LTP])
                    master_context[TYPE][LIVE][NEW_LTP] = float(val)                        
                    break
                #else:
                #    print(f"scrip is {master_context[TYPE][LIVE][CTX_SCRIP]}")

            if(val == -1):
                print("Error updating ltp")
                print(master_context[TYPE][LIVE][CTX_SCRIP])
                return(-1)

    def update_orders(self,ctx_type):
        global log
        global delta
        global trade_context
        global master_context
        global ACT
        global PAS

        TYPE     = ctx_type
        LIVE     = 0
        SPOT_LTP = 0
        FUND     = 1
        SCRIP    = 0
       
        log.info("AM-4010")
        
        if(master_context[TYPE][LIVE] != []):
            master_context[TYPE][LIVE][SCRIP] = -1
        
        # update Active orders and update trade context based on active orders
        for order in master_context[TYPE][ACT]: # format ['C-BTC-34750-120522', 1, -1.0]
            order[ORDER_LTP]    = float(self.delta.get_current_value(order[SCRIP]))                        # LTP
            if(order[ORDER_LTP] == -1):
                print("Update ltp for active order "+order[0]+ "failed")
                log.error("AM-4012-"+order[0])
                return(-1)
        for order in master_context[TYPE][PAS]:
            if(order[SCRIP] == 0 or order[SCRIP] == -1): # no passive order
                return(0)

            order[ORDER_LTP]    = float(self.delta.get_current_value(order[SCRIP]))                        # LTP
            if(order[ORDER_LTP] == -1):
                print("Update ltp for inactive order "+order[SCRIP]+ "failed")
                log.error("AM-4013-"+order[SCRIP])
                return(-1)

        #print(f"active orders {master_context[TYPE][ACT]}")

    def update_context(self):
        global log
        global delta
        global trade_context
        global master_context
        global CE
        global PE 
        COIN    = 0

        LIVE     = 0
        SPOT_LTP = 0
        FUND     = 1
        SCRIP    = 0
       
        master_context[SHEET][SPOT_LTP]    = float(delta.get_current_value(master_config[SHEET][COIN]+"USD"))      # spot  price 
        if(master_context[SHEET][SPOT_LTP] == -1):
            log.error("AM-4014"+(master_config[SHEET][COIN]+"USD"))
            print("spot ltp failed")
            return(-1)
        master_context[SHEET][SPOT_LTP]    = float(float(master_context[SHEET][SPOT_LTP]))
        
        result = account_context.validate_atm(CE)
        if(result == -1):
            print("validate ce failed")
            return(-1)
        
        result = account_context.validate_atm(PE)
        if(result == -1):
            print("validate pe failed")
            return(-1)

        master_context[SHEET][FUND]    = self.delta.get_available_balance()                 # Funds
        if(master_context[SHEET][FUND] == -1):
            log.error(f"AM-4019 {master_context[SHEET][FUND]}")
            #print("fund update failed") # unblock failed
            #return(-1) # unblock this later
        master_context[SHEET][FUND]    = float(master_context[SHEET][FUND])
        
        log.info("AM-4020")
        return(0)

def check_internet():
    host_list = ["google.com","delta.exchange"]
    for site in host_list:
        try:
            response = os.system("ping -c 1 " + site)
        except socket.timeout:
            print(f"Socket error: Unable to ping {site}")
        return(response)

def scheduler(config,context,delta):
    global order_status_change
    #print("\nStart time")
    global master_config
    global master_context
    SHEET   = 0 # list level 1
    COIN    = 0
    FREQ    = 2
    LOT     = 8
    FUND    = 1
    STRATEGY= 3

    #global trade_context
    global master_context

    if(order_status_change == 1):
        print(datetime.now())
        order_status_change= 0
    else:
        print(datetime.now(),end='\r')
    
    result = -1
    # check active orders
    response = accounts.get_order_history()
    if(response == -1):
        print("Active order fetching failed")

    # check placed orders
    out = accounts.get_live_orders()
    if(out == -1):
        print("Placed order fetching failed")
    
    result = context.update_context()
    
    #master_config[SHEET] = -1
    #master_config[SHEET] = config.read_config()
    #if(master_config[SHEET] == -1):
    #    return(-1)
    
    frequency = 15
    frequency = int(master_config[SHEET][FREQ]) # frequency
    threading.Timer((frequency*60), scheduler,[config,context,delta]).start()
    
    # check if balance is low
    if(float(master_context[SHEET][FUND])<1.0):
        return(-1)
    
    #if(response != -1):
    #    master_context[TYPE][ACT] = response[:] 
    
    # check active orders
    #if(out != -1):
    #    master_context[TYPE][PAS] = out[:] 
         
    # call strategy
    strategy_chosen = strategy_run()
    result = -1
    result = getattr(strategy_chosen,master_config[SHEET][STRATEGY])(context,master_config[SHEET][LOT],master_config[SHEET][COIN])
    if(result == -1):
        print("Strategy run failed")
    
    # update configs
    #for i in range(1,5):
    #    result = context.update_orders(i)
    #    if(result == -1):
    #        return(-1)

    # update balance sheet
    result = delta.get_available_balance()
    if(result == -1):
        return(-1)
    else:
        master_context[SHEET][FUND] = result


def main():
    global master_config
    SHEET = 0 # level 1 list
    COIN  = 0
    EXPIRY= 1
    URL   = 5
    KEY   = 6
    SECRET= 7    
    FUND  = 1

    global delta_client
    global delta
    global deltaorder
    global accounts
    global master_context
    global log
    global context
    global util

    print("start")
    # 1.create log file
    util = utilities()
    log = util.create_log_file()
    log.info("AM-1000")
    
    # 2.check internet
    response = -1
    while(response == -1):
        response = check_internet()
        if(response == 0):
            break
        time.sleep(10)

    log.info("AM-1001")

    # 3.get authorization
    # 4.get configurations
    config = get_config()
    master_config[SHEET] = config.read_config()
    if(master_config[SHEET] == -1):
        return

    # 5.initiate delta client
    delta_client  = DeltaRestClient(
        base_url  =master_config[SHEET][URL],
        api_key   =master_config[SHEET][KEY],
        api_secret=master_config[SHEET][SECRET]
        )
    # 6.get stats balance 
    delta = None
    delta = delta_stats(delta_client,log)
    if(delta is None):
        log.error("AM-1011")
        exit(0)
    else:
        log.info("AM-1010")

    #print("Product id:")
    result = -1
    result = float(delta.get_available_balance())
    if(result != -1):
        master_context[SHEET][FUND] = result
    else:
        print("Low Balance")
        #exit(0)
    
    # 7. place orders init
    deltaorder = delta_orders(delta_client,log)

    # 8. Orders tracker init 
    accounts = delta_accounts(delta_client,log)

    # 9.get active orders
    response = accounts.get_order_history()

    # 10.get passive orders
    response = accounts.get_live_orders()
    
    # 11.Get context
    context = account_context(master_config[SHEET][COIN],master_config[SHEET][EXPIRY])
    
    for i in range(1,5):
        response = -1
        response = context.update_orders(i)
        if(response == -1):
            log.error("AM-1020")
            exit(0)
    response = context.update_context()
    
    #12. call scheduler
    scheduler(config,context,delta)
    
if __name__ == "__main__":
    main()

#print(DeltaRestClient.__file__)

