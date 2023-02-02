#!/usr/bin/python3
#import os
#import time
import hashlib
import hmac
import base64
#from delta_rest_client import DeltaRestClient
import requests
from datetime import datetime, timedelta

#import main_code.master_config ,main_code.master_context,main_code.master_handle,main_code.master_lock
import header
from header import master_config,master_context,master_handle,master_lock

MASTER_LOCK_CFG = 0
MASTER_LOCK_CTX = 1
MASTER_LOCK_HDL = 2

from requests import status_codes
from gettimer import refine_order_list,next_expiry,second_next_expiry
from googlesheet import status_sheet

log = 0
MAX_CTX = 5 # ce, pe,cem,pem +1(for range )
from delta_rest_client import DeltaRestClient, create_order_format, cancel_order_format, round_by_tick_size, OrderType, TimeInForce

#config = get_config()
#delta_client = DeltaRestClient(
#    base_url=config.url,
#    api_key=config.apikey,
#    api_secret=config.apisecret
#)

#delta_client = DeltaRestClient(
#    base_url='https://api.delta.exchange',
#    api_key='bR2nfO9',
#    api_secret='qB5eFB5eF89yBWPC7'

# Active  format : [['C-BTC-29700-110622', -1, '262.50000000',   60541, 0,    '262.50000000']]
# Passive format : [['C-BTC-29000-110622',  1, '285.05447068', '363.6', 60372, 829539015    ]]
DQUOTE      = 'quoting_asset'
DCURRENCY   = 'symbol'#'settling_asset'
DBALANCE    = 'balance'
DPID        = 'product_id'
DSYMBOL     = 'product_symbol'
DOSIZE       = 'order_size'
DPRICE      = 'entry_price'
DSIDE       = 'side'
DSIZE       = 'size'
DID         = 'id'
DSTOP       = 'stop_price'
DSTATE      = 'state'
DRESULT     = 'result'
DLIMIT      = 'limit_price'
class delta_stats:
    global log
    def __init__(self,delta_client,log_var):
        self.product_id = 84                                 #USDT
        self.delta_client = delta_client
        log = log_var
        #log.info("AD-1000")
        self.log = log_var

    def get_available_balance(self):
        self.log.info("AD-1010")
        date = datetime.now()
        product = 0
        product = self.delta_client.get_product(self.product_id)  # Current Instrument
        if(product ==0):
            self.log.info("AD-1021")
        else:
            self.log.info("AD-1020")

        if((type(product) is dict) and (product is not [])): 
            settling_asset = product[DQUOTE][DCURRENCY]      # Currency in which the pnl will be realised
        else:
            print(f"currency type cannot be fetched from {type(product)} {product[DQUOTE][DCURRENCY]}")
        #response = delta_client.get_transactions(settling_asset[DID])
        #print(response)
        response = None
        response = self.delta_client.get_balances(product[DID])#settling_asset[DID])

        #update balance in the sheet
        status = status_sheet()
        #print(response[DBALANCE])
        #print(date.strftime("%d-%b-%y"))
        #print(date.strftime("%H:%M %d/%m/%Y"))
        if(response == -1 or response == None):
            return(-1)
        status.update_balance(response[DBALANCE],date.strftime("%d-%b-%y"),date.strftime("%H:%M %d/%m/%Y"))

        return(response[DBALANCE])
    
    def get_product_id(self,symbol):
        try:
            response = self.delta_client.get_ticker(symbol)
            if(response != None):
                return(response[DPID])
            else:
                print("product id is Null,may be expiry date invalid for "+symbol)
                return(0)
        except requests.exceptions.HTTPError as e:
            print("Get Product id,failed the error: " + str(e.response.code))
            return(-1)

        #print(response)

    def get_current_value(self,symbol):
        response = self.delta_client.get_ticker(symbol)
        if(response == [] or response == None or response == -1):
            return(-1)
        #print(f"ltp response : {response}")
        return(response['mark_price'])

    def get_pnl(self,product_id,margin):
        response = self.delta_client.change_position_margin(product_id, margin)
        return(response)

class delta_accounts:
    global log

    def __init__(self,delta_client,log_var):
        self.query = { "contract_types": "put_options,call_options" }
        self.page_size = 50
        self.last_closed_order = '0'
        self.delta_client = delta_client
        log = log_var

    def parse_passive_orders(self,order,TYPE):
        PASSIVE = 2
        
        if(type(order) is int):
            print(f"cant parse order {order} ..returning")
            return(-1)
        order_item = []
        if('pending' in order[DSTATE] and order != -1 or order != []):
            order_item.append(order[DSYMBOL])
            if('sell' in order[DSIDE]):
                order_item.append(int(-1*order[DSIZE]))
            elif('buy' in order[DSIDE]):
                order_item.append(int(1*order[DSIZE]))
            ltp = 0
            if(order[DSTOP] != None):
                ltp = float(order[DSTOP])
            elif(order[DLIMIT] != None):
                ltp = float(order[DLIMIT])
            else:
                print("Could not parse order price in order {order}")
                return(-1)

            #ltp = stats.get_current_value(order[DSYMBOL])
            order_item.append(ltp)  # LTP ,to be filled during update calls

            order_item.append(ltp)
            order_item.append(order[DPID])
            order_item.append(order[DID])
            if(header.master_context[TYPE] == []):
                print(f"list for type:{TYPE} is [] in {header.master_context}")
                return(1)
            elif(header.master_context[TYPE][PASSIVE] != []):
                header.master_context[TYPE][PASSIVE].append(order_item)
                return(1)
            else:
                header.master_context[TYPE][PASSIVE].insert(0,order_item)
                return(1)
        return(-1)

    def get_order_history(self):
        global MAX_CTX
        global master_context
        ORDER_LOT   = 1

        ACTIVE = 1
        DIR_ID = 4 # C-BTC or P-BTC
        EXP    = 5 # daily or monthly
        ctx_type = 0

        #master_context[2][ACTIVE] = [['P-BTC-28750-120622', -1, '65.0000000',   60523, 0,    '65']]
        #return(1)
        # Passive format : [['C-BTC-29000-110622',  1, '285.05447068', '363.6', 60372, 829539015    ]]
        exp1 = next_expiry() # next day expiry
        exp2 = second_next_expiry() # second next day expiry
        #self.query = { "contract_type": "put_options,call_options" }
        self.query = {"side": "buy,sell"}
        self.page_size = 100 # changing this from 50 to avoid exceptions(try)
        response = self.delta_client.fills(self.query, self.page_size)
        if(response == -1):
            print("Fill response is empty ..returning")
            return(-1)
        
        fills = response[DRESULT]
        # fills will have stale entries , so remove them based on expiry dates
        effective_date = datetime.now()
        closure_time = effective_date.replace(hour=17, minute=15, second=0, microsecond=0)
        if(effective_date >= closure_time):
            effective_date = datetime.now() + timedelta(days=1)
        
        header.master_lock[MASTER_LOCK_CTX] = 1  # lock context list
        for i in range(1,MAX_CTX):
            header.master_context[i][ACTIVE] = []
        header.master_lock[MASTER_LOCK_CTX] = 1  # unlock context list

        while(fills is not []):
            #if((not fills[-1]['order_id'].isnumeric()) or (int(self.last_closed_order) < int(fills[-1]['order_id']))):
            if(True):
                for order in response[DRESULT]:
                    scrip = order[DSYMBOL]
                    #print(scrip)
                    expdate = scrip.split('-')
                    if(len(expdate) != 4):
                        continue
                    elif(len(expdate) == 4):
                        expdate = expdate[3]
                    if(datetime.strptime(expdate,"%d%m%y").date()<effective_date.date()): # this is a stale order
                        continue
  
                    header.master_lock[MASTER_LOCK_CTX] = 1  # lock context list
                    for i in range(1,MAX_CTX):
                        if(header.master_config[i][DIR_ID] in scrip and (exp1 in scrip  or exp2 in scrip)):
                            ctx_type = i
                            break           # this is required when day expiry and month expiry are the same 
                    header.master_lock[MASTER_LOCK_CTX] = 1  # unlock context list
                    if(ctx_type == 0):
                        #print(f"no match for {header.master_config[1][DIR_ID]} or {header.master_config[1][EXP]} in {scrip} ")
                        return(0) # not a big failure ,so return 0 instead of -1

                    if('buy' in order[DSIDE]):
                        size = int(float(order['meta_data'][DOSIZE]))
                    elif('sell' in order[DSIDE]):
                        size = -1*(int(float(order['meta_data'][DOSIZE])))
                    else:
                        print("Error in getting the direction:")
                        print(order[DSIDE])
                        return(-1)
                    price = order['meta_data']['new_position'].get(DPRICE)
                    if(price != None):
                        price = float(price)
                    if(header.master_context[ctx_type][ACTIVE] == []):
                        item=[]
                        item.append(order[DSYMBOL])
                        item.append(int(size))
                        #price = order['meta_data']['new_position'].get(DPRICE)
                        item.append(price) # LTP, will be updated over time 
                        item.append(price) # Trigger
                        item.append(order[DPID])
                        item.append(0) # for future use
                        #item.append(price) # entry price as all other prices are changing 
                        header.master_context[ctx_type][ACTIVE].append(item)
                    else:
                        if(type(header.master_context[ctx_type][ACTIVE]) is not list):
                            print(f"Active list for {ctx_type} is wrong:{header.master_context[ctx_type][ACTIVE]}")
                            return(-1)


                        index = [idx for idx,s in enumerate(header.master_context[ctx_type][ACTIVE]) if order[DSYMBOL] in s[0]]
                        if(index == []):
                            item = []
                            item.append(order[DSYMBOL])
                            item.append(int(size))
                            #price = 0
                            #price = order['meta_data']['new_position'].get(DPRICE)
                            item.append(price) # LTP ...will be updated over time 
                            item.append(price) # Trigger price
                            item.append(order[DPID])
                            item.append(0) # for future use
                            #item.append(price) # entr price as all other prices are changing 
                            header.master_context[ctx_type][ACTIVE].append(item)
                        #elif((header.master_context[ctx_type][ACTIVE][index[0]][1] + size) == 0): # done below ,seperately,to avoid, 
                            #del(header.master_context[ctx_type][ACTIVE][index[0]]) # prioiritzing old closed orders over new orders
                        else:
                            if(header.master_context[ctx_type][ACTIVE][index[0]][2]==None):
                                header.master_context[ctx_type][ACTIVE][index[0]][2] = price
                                header.master_context[ctx_type][ACTIVE][index[0]][3] = price
                            header.master_context[ctx_type][ACTIVE][index[0]][1] = header.master_context[ctx_type][ACTIVE][index[0]][1] + size
            else:
                break
            
            fills = []
            after_cursor_for_next_page = response["meta"]["after"]
            if(after_cursor_for_next_page == None):
                break
            response = self.delta_client.fills(self.query, page_size=100, after=after_cursor_for_next_page)
            
            if(response == -1):
                response = self.delta_client.fills(self.query, page_size=50, after=after_cursor_for_next_page)
                if(response == -1):
                    return(-1)
            fills = response[DRESULT]

        fills = response[DRESULT]

        for i in range(1,MAX_CTX):
            header.master_context[i][ACTIVE] = [a_order for a_order in header.master_context[i][ACTIVE] if a_order[ORDER_LOT] != 0]
        
        if(ctx_type == 0):
            return(0)
        else:
            return(header.master_context[ctx_type][ACTIVE])
        #return(fills)

        #orders = refine_order_list(active_order)
        #return(orders)
    
    def get_live_orders(self):
        global log
        
        COIN_DIR = 4 # C-BTC
        EXP = 5 # 270522
        PASSIVE = 2
        ctx_type = 0
        #master_context[1][PASSIVE] = [['C-BTC-29400-110622', -1, '21.8794643', '5.7', 60543, 830230300], ['C-BTC-29400-110622', -1, '20.8794643', '5.8', 60543, 830229484]]
        #return(11)
        stats = delta_stats(self.delta_client,log)

        header.master_lock[MASTER_LOCK_CTX] = 1  # lock context list
        for i in range(1,MAX_CTX):
            header.master_context[i][PASSIVE] = []
        header.master_lock[MASTER_LOCK_CTX] = 1  # unlock context list
        response = self.delta_client.get_live_orders()
        if(response == -1 or response == None):
            print(f"live orders call returned {response}")
            return(-1)
            
        exp1 = next_expiry() # second next day expiry
        exp2 = second_next_expiry() # second next day expiry
        for order in response:
            order_item = []
            if('pending' in order[DSTATE] or 'open' in order[DSTATE]):
                header.master_lock[MASTER_LOCK_CTX] = 1  # lock context list
                for i in range(1,MAX_CTX):
                    scr = order[DSYMBOL]
                    if(header.master_config[i][COIN_DIR] in scr and (exp1 in scr or exp2 in scr)):
                        ctx_type = i
                        break           # this is required when day expiry and month expiry are the same
                header.master_lock[MASTER_LOCK_CTX] = 1  # unlock context list
                if(ctx_type <1):
                    return(-1)

                order_item.append(order[DSYMBOL])
                if('sell' in order[DSIDE]):
                    order_item.append(int(-1*order[DSIZE]))
                elif('buy' in order[DSIDE]):
                    order_item.append(int(1*order[DSIZE]))
            ltp = stats.get_current_value(order[DSYMBOL]) 
            order_item.append(ltp)  # LTP ,to be filled during update calls
            
            if(order[DSTOP]==None):
                order_item.append(order[DLIMIT])
            else:
                order_item.append(order[DSTOP])

            order_item.append(order[DPID])
            order_item.append(order[DID])
            #print(order_item)
            if(header.master_context[ctx_type] == []):
                print(header.master_context[ctx_type])
            elif(type(header.master_context[ctx_type])  is list):
                if(header.master_context[ctx_type][PASSIVE] != []):
                    header.master_context[ctx_type][PASSIVE].append(order_item)
                else:
                    header.master_context[ctx_type][PASSIVE].insert(0,order_item)
        #print("Passive orders :") # [symbol,side*size,ltp,trigger_price,product_id,order_id]
        if(ctx_type == 0):
            return(0)
        else:
            return(header.master_context[ctx_type][PASSIVE])
        #return(0) # fix this return code 

    def get_order_book(self,product_id):
        response = self.delta_client.get_l2_orderbook(product_id)
        #print("order book :")
        return(response)

    def get_open_positions(self,product_id):
        #response = self.delta_client.get_position(product_id)
        response = self.delta_client.get_margined_position(product_id)
        return(response['realized_pnl'])

    def parse_update_orders(self,orders):
        for item in orders:
            print(item['product']['symbol'])
            print(item[DSIDE])
            print(item[DSIZE])
            print(item['created_at'])
            print(item[DSTATE])
            print(item['product']['symbol'])
            print("PL:0")
            print(item['paid_commission'])

class delta_orders:
    global log
    def __init__(self,delta_client,log_var):
        self.delta_client = delta_client
        log = log_var

    def get_order_history(self):
        print(item['paid_commission'])
    
    def place_order(self,prod_id,lotsize,direction,lprice):
        leverage = 100
        if('buy' in direction):
            leverage = 10
        try:
            response = self.delta_client.set_leverage(prod_id, leverage)
        except requests.exceptions.HTTPError as e:
            print("Leverage set failed:(" + str(e.response.status_code) +")"+ status_codes._codes[e.response.status_code][0])
            return(-1)
        # Place order and place stop order
        try:
            lprice = round(float(lprice),1)
            order_limit_gtc = self.delta_client.place_order(
                product_id=prod_id, order_type="limit_order",size=str(lotsize), side=direction, limit_price=lprice, time_in_force='gtc')
            return(order_limit_gtc)
        except requests.exceptions.HTTPError as e:
            print("Limit order failed with the error: " + str(e.response.code))
            return(-1)

        return(0)

    def stoploss_order(self,sprice):
        try:
            sprice = round(float(lprice),1)
            stop_order = self.delta_client.place_stop_order(
                product_id, order_type=ordertype.market, size=10, side='sell', stop_price=str(sprice))
        except requests.exceptions.httperror as e:
            print("stoploss order failed with the error: " + str(e.response.code))
    
    def stoploss_limit(self,prod_id,lotsize,direction,lprice,sprice,ltp):
        leverage = 100
        # Pending :check if values are numberic
        if('sell' not in direction and 'buy' not in direction):
            print("direction should be either buy or sell and not ",direction)
            return(-1)
        if('buy' in direction):
            if((lprice<sprice) or (lprice<ltp) or (sprice<ltp)): 
                print(f"arguments invalid: For 'buy', required conditon is ltp{ltp} < sprice{sprice} < lprice{lprice}")
                return(-1)
            leverage = 10

        if('sell' in direction):
            if((lprice>sprice) or (lprice>ltp) or (sprice>ltp)): 
                print(f"arguments invalid: for 'sell' ,required conditon is ltp{ltp} > sprice{sprice} > lprice{lprice}")
                #return(-1)
            leverage = 100
        
        try:
            response = self.delta_client.set_leverage(prod_id, leverage)
        except requests.exceptions.HTTPError as e:
            print("Leverage set failed:(" + str(e.response.status_code) +")"+ status_codes._codes[e.response.status_code][0])
            return(-1)
        #print(f"prod {prod_id} limit {lprice} lot {lotsize} side {direction} stop {sprice}")
        stop_order = ""
        try:
            lprice = round(float(lprice),1)
            sprice = round(float(sprice),1)
            stop_order = self.delta_client.place_stop_order(product_id=prod_id, order_type="limit_order",limit_price=str(lprice), size=str(lotsize), side=direction, stop_price=str(sprice))
            return(stop_order)
        except requests.exceptions.HTTPError as e:
            print("Sl-limit order failed:(" + str(e.response.status_code) +")"+ status_codes._codes[e.response.status_code][0])
            print(e.response)
        
        return(-1)
    
    def market_order(self, prod_id,lot_size,direction):
        print(f"prod = {prod_id} lot {lot_size} dir {direction}")
        if('sell' in direction):
            try:
                response = self.delta_client.set_leverage(prod_id, 100)
            except requests.exceptions.HTTPError as e:
                print("Leverage set failed:(" + str(e.response.status_code) +")"+ status_codes._codes[e.response.status_code][0])
                #return(-1)
        try:
            m_order = self.delta_client.place_order(
                product_id=prod_id, order_type="market_order", size=lot_size, side=direction,time_in_force="fok")
            #print(stop_order)
            return(m_order)
        except requests.exceptions.HTTPError as e:
            print("Market order failed:(" + str(e.response.status_code) +")"+ status_codes._codes[e.response.status_code][0])
            return(-1)
    

    def cancel(self,prod_id,order_id):
        try:
            response = self.delta_client.cancel_order(prod_id, order_id)
            #return(response)
            return(0)
        except requests.exceptions.HTTPError as e:
            print(f"Cancel order failed with the error:{e.response.status_code} {e.response.reason}")
            return(-1)

    def trailing_sl_order(self):
        try:
            trailing_stop_order = self.delta_client.place_stop_order(
                product_id=product_id,
                size=10,
                side='sell',
                order_type=OrderType.MARKET,
                trail_amount=20,
                isTrailingStopLoss=True
            )
        except requests.exceptions.HTTPError as e:
            print("trailing sl order failed with the error: " + str(e.response.code))



#print(DeltaRestClient.__file__)
#accounts = delta_accounts()
#orders = accounts.get_live_orders()
#accounts.parse_update_orders(orders)
#accounts.get_order_history()
#print("%.2f USDT"%float(delta.get_available_balance()))
#print(delta.get_current_value("C-BTC-34750-120522"))
#print(delta.get_current_value("P-BTC-40000-180422"))
#print(delta.get_order_history()[1]['meta_data']['new_position']['realized_pnl'])
#order = delta_orders
#order.stoploss_limit(1,'sell',1,10)

