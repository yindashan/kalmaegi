#!/usr/bin/python
# -*- coding:utf-8 -*-

import redis
import MySQLdb
import json, logging
import traceback

from redis.connection import ConnectionPool, BlockingConnectionPool
from redis.exceptions import RedisError

# our own lib
from settings import LOG_PATH, PORT 
from settings import REDIS_HOST, REDIS_PORT, REDIS_DB_NUM, REDIS_PASSWORD
from settings import DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD
from log_record import initlog

#数据库中读取　1.监控项　2.应用服务和IP地址的对应关系   
def load_rules():
    logger = logging.getLogger("monitor.autoload")
    logger.info(u"从数据库读取配置信息.")
    
    pool = BlockingConnectionPool(max_connections=5, timeout=5, socket_timeout=5, \
            host=REDIS_HOST, port=REDIS_PORT, db=REDIS_DB_NUM, password=REDIS_PASSWORD)
    redis_db = redis.StrictRedis(connection_pool=pool)
    
    conn = None
    try:
        conn = MySQLdb.connect(host=DB_HOST, port=DB_PORT, db=DB_NAME, \
            user=DB_USER, passwd=DB_PASSWORD, charset='utf8')
    except BaseException, e:
        logger.error("The server can't connect to mysql." + str(e))
        return
        
    cur = conn.cursor()
    #1.读取监控项
    sql = "select m.id,m.monitor_type,m.var_name,m.formula,m.warning_threshold,"
    sql += "m.critical_threshold,m.desc,a.app_name " 
    sql += " from monitor_item m,app_service a where a.id = m.app_id"
    cur.execute(sql) 
    res = cur.fetchall()
    #conn.commit()
    app_rules = {}
    for item in res:
        app = item[7]
        if app not in app_rules:
            app_rules[app] = []
        temp = {}
        temp['id'] = item[0]
        temp['monitor_type'] = item[1]
        temp['var_name'] = item[2]
        temp['formula'] = item[3]
        temp['warning_threshold'] = item[4]
        temp['critical_threshold'] = item[5]
        temp['desc'] = item[6]
        app_rules[app].append(temp)
        
    for app in app_rules:
        redis_db.hset('app_rules', app, json.dumps(app_rules[app]))
        
    #2.读取应用服务和IP地址的对应关系
    sql = "select a.app_name,a.ip_list,a.email_list,a.mobile_list,a.check_interval,a.max_check_attempts from app_service a"
    cur.execute(sql) 
    res = cur.fetchall()
    cur.close()
    conn.close()
    app_iplist = []
    for item in res:
        temp = {}
        temp['name'] = item[0]
        ip_list = item[1].strip()
        email_list = item[2].strip()
        mobile_list = item[3].strip()
        temp['check_interval'] = item[4]
        temp['max_check_attempts'] = item[5]
        
        temp['ip_list'] = []
        if ip_list != '':                                # 目前情况下ip_list 不允许为空
            temp['ip_list'] = ip_list.split(',')
            
        temp['email_list'] = []   
        if email_list != '':
            temp['email_list'] = email_list.split(',')
            
        temp['mobile_list'] = []   
        if mobile_list != '':
            temp['mobile_list'] = mobile_list.split(',')
            
        app_iplist.append(temp)
    redis_db.set('app_info', json.dumps(app_iplist))

def main():
    print "server is starting... ..."
    initlog('monitor.autoload', LOG_PATH, 'autoload.log', logLevel=logging.INFO)
    load_rules()

#------------------------- start---------------------------
if __name__ == '__main__':
    main()
