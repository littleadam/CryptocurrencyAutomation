#!/usr/bin/env python3

#import logging
from datetime import datetime, timedelta
#from logging.handlers import TimedRotatingFileHandler
#from header import *
#import maincode
from header import master_config,master_context,master_handle,master_lock

def next_expiry():
    global log
    effective_date = datetime.now()
    closure_time = effective_date.replace(hour=17, minute=15, second=0, microsecond=0)
    if(effective_date >= closure_time):
        effective_date = datetime.now() + timedelta(days=1)

    return(effective_date.strftime("%d%m%y"))

def second_next_expiry():
    global log
    effective_date = datetime.now()
    closure_time = effective_date.replace(hour=17, minute=15, second=0, microsecond=0)
    if(effective_date >= closure_time):
        effective_date = datetime.now() + timedelta(days=2)
    
    if(effective_date < closure_time):
        effective_date = datetime.now() + timedelta(days=1)

    return(effective_date.strftime("%d%m%y"))

def next_week_expiry():
    global log
    effective_date = datetime.now()
    closure_time = effective_date.replace(hour=17, minute=15, second=0, microsecond=0)
    if(effective_date >= closure_time):
        effective_date = datetime.now() + timedelta(days=1)
    effective_date = effective_date + timedelta( (4-effective_date.weekday()) % 7 )
    return(effective_date.strftime("%d%m%y"))

def next_month_expiry():
    global log
    effective_date = datetime.now()
    closure_time = effective_date.replace(hour=17, minute=15, second=0, microsecond=0)
    if(effective_date >= closure_time):
        effective_date = datetime.now() + timedelta(days=1)
    effective_date = effective_date + timedelta( (4-effective_date.weekday()) % 7 )
    monthly_expiry = effective_date

    while(monthly_expiry.month == effective_date.month):
        effective_date = monthly_expiry
        monthly_expiry = effective_date +timedelta(days=7)

    return(effective_date.strftime("%d%m%y"))

def form_symbol(direction,coiner,value,expiry_type,multiplier):
    global log
    if(direction == 'P'):
        factor = 0
    elif(direction == 'C'):
        factor = 1
    
    if(expiry_type == 'month'):
        eday = next_month_expiry()
    elif(expiry_type == 'week'):
        eday = next_week_expiry()
    elif(expiry_type == 'day' or expiry_type == 'secondday'):
        eday = next_expiry()
    symbol = direction+'-'+coiner+'-'+str((int(value/multiplier)+factor)*multiplier)+'-'+str(eday)
    return(symbol)

def split_symbol(sym):
    global log
    return(sym.split('-'))

def refine_order_list(active_orders):
    global log
    refined_item = []
    effective_date = datetime.datetime.now()
    closure_time = effective_date.replace(hour=17, minute=15, second=0, microsecond=0)
    if(effective_date >= closure_time):
        effective_date = datetime.datetime.now() + timedelta(days=1)

    for item in active_orders:
        expdate = item[0].split('-')[3]
        if(datetime.datetime.strptime(expdate,"%d%m%y").date()>=effective_date.date()):
                refined_item.append(item)
    return(refined_item)

def create_log_file():
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

#logging.info('your text goes here')
#logging.error('your text goes here')
#logging.debug('your text goes here')

