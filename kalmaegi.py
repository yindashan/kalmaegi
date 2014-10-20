#!/usr/bin/python
# -*- coding:utf-8 -*-

####################################
#  kalmaegi
#  1) 收集应用状态
#  2) 收集host硬件信息
####################################

# 关于错误码说明
# 1XX
# ErrorCode 101   ------> 配置错误 　可能原因: 1.此应用没有加入监控配置 2.此应用没有对应的监控项
# 2XX
# ErrorCode 201   ------> 请求的状态文件信息不存在    可能原因:1.应用服务器没有按时提交请求　２.nagois服务器多次请求，导致文件已被消费
# 3XX
# ErrorCode 301   ------> 计算过程发生错误　可能原因:1.变量值缺失 2.计算公式和变量名书写错误
# 4XX
# ErrorCode 401   ------> json 字符串格式错误
# ErrorCode 402   ------> 监控项对应值计算错误

# 5XX
# ErrorCode 501   ------> 连接redis发生异常

import sys
import redis, time
import json, logging
import traceback
import tornado.ioloop
import tornado.web

from xml.dom import minidom

from redis import BlockingConnectionPool
from redis import RedisError
from datetime import datetime

# our own lib
from settings import HOST, PORT, LOG_HOST, LOG_PORT 
from settings import REDIS_HOST, REDIS_PORT, REDIS_DB_NUM, REDIS_PASSWORD
from socket_log  import initlog
from save_data import save_point_data


class Message(object):
    def __init__(self, content):
        self.content = content
        self.occur_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    def jsonate(self):
        temp = {'content': self.content, 'occur_time': self.occur_time}
        return json.dumps(temp)

def get_remote_ip(request):
    if 'X-Forwarded-For' in request.headers:
        return request.headers['X-Forwarded-For']
    else:
        return request.remote_ip
        
def split_string(obj):
    if isinstance(obj, basestring):
        obj = obj.strip()
        if obj:
            return obj.split(',')
    else:
        return []
        

# 封装应用上报的参数　        
class AppReport(object):
    def __init__(self):
        # 应用名称
        self.app_name = ''
        # 主机ID
        self.host = ''
        # 状态值键值字典
        self.data_dict = {}
        
    def __unicode__(self):
        return u"应用名称:%s, 主机ID:%s，状态值:%s" % (self.app_name, self.host, str(self.data_dict))
        
def _deal_report(handler, report):
    logger = logging.getLogger("monitor.all")
                
    # 如果host_id 不在应用要求的host列表中，则不处理
    host_list = handler.redis_db.hget(report.app_name + '_config', 'host_list')
    if host_list:
        host_list = host_list.split(',')
    else:
        host_list = []
        
    if report.host in host_list:
        rules = handler.redis_db.hget('app_rules', report.app_name)
        if rules == None:
            logger.error(u'配置错误,无法获取应用%s的监控项信息，附加信息:%s', \
                report.app_name, unicode(report))
            return 101
        
        res = {}
        res['appname'] = report.app_name
        res['host'] = report.host
        res['monitor'] = []
        app_rules = json.loads(rules)
        for rule in app_rules:
            m_item = {}
            m_item['id'] = rule['id']
            m_item['warning'] = rule['warning_threshold']
            m_item['critical'] = rule['critical_threshold']
            m_item['desc'] = rule['desc']
            try:
                m_item['value'] = compute_value(rule, report.data_dict)
            except BaseException, e:
                logger.error(u'应用%s监控项对应数值计算过程发生错误，附加信息:%s\n,%s', \
                    report.app_name, unicode(report), traceback.format_exc())
                return 402
            res['monitor'].append(m_item)
            
        # -------------------------------------------
        # 保存监控点数据   
        save_point_data(handler, res)
        # -------------------------------------------
        handler.redis_db.set(report.app_name + '_' + report.host, json.dumps(res))  
        logger.info(u'成功处理应用:%s，主机:%s上报的状态信息', report.app_name, report.host)
        
    return 0
        

# 处理应用上报的状态信息        
def deal_report(handler, report):
    
    res = _deal_report(handler, report)
    if res!= 0:
        return res
    
    # -------------  额外逻辑 ----------  
    # 对于主机状态检查而言，它使用同一个应用名称进行上报
    if report.app_name == 'HOST_STATUS':
        # 如果应用有子应用则递归的进行处理
        app_list = handler.redis_db.hget('_hs_host_app', report.host)
        if app_list:
            for app in app_list.split(','):
                if app == 'HOST_STATUS':
                    continue
                    
                report.app_name = app
                res =  _deal_report(handler, report)
                if res != 0:
                    return res
    
    return 0

# 1. 处理上报的硬件信息
class HardwareHandler(tornado.web.RequestHandler):
    def initialize(self):
        # 显式使用连接池,阻塞式连接池
        # 注:socket_timeout　--创建socket，或者读写socket的超时
        # timeout    --从queue中取连接的超时
        pool = BlockingConnectionPool(max_connections=5, timeout=5, socket_timeout=5, \
            host=REDIS_HOST, port=REDIS_PORT, db=REDIS_DB_NUM, password=REDIS_PASSWORD)
        self.redis_db = redis.StrictRedis(connection_pool=pool)
        
    def post(self):
        logger = logging.getLogger("monitor.all")
        logger.info(u"接收到硬件信息上报请求, 来源IP:%s, POST数据:%s",
            get_remote_ip(self.request), self.request.body)
        
        pipe = self.redis_db.pipeline()
        
        try:
            dd = json.loads(self.request.body)
            # 1) 保存主机硬件信息
            key  = dd['host_id'] + '_hc'
            ip = None
            for item in dd['hardware']:
                if item['name'] == 'IP':
                    # ***判断IP是否变更***
                    old_ip = self.redis_db.hget(key, 'IP')
                    ip = item['value']
                    pipe.hset('host_ip', dd['host_id'], ip)
                    if item['value'] != old_ip and old_ip != None:
                        msg = u'发现IP变更,host_id:%s,原IP:%s,新IP:%s' %  (dd['host_id'], old_ip, item['value'])
                        pipe.rpush('message', Message(msg).jsonate())
                        
                pipe.hset(key, item['name'], item['value'])
                
            # 设置失效时间 2 hours
            pipe.expire(key, 60*60*2)
            
            # 2) 保存IP和 host_id 的对应关系
            # ***判断IP是否重复***
            old_host_id = self.redis_db.hget('ip_host', ip)
            if dd['host_id'] != old_host_id and old_host_id != None:
                # 发出通知消息
                msg = u'发现IP重复,IP:%s,原host_id:%s,新host_id:%s' % (ip, old_host_id, dd['host_id'])
                pipe.rpush('message', Message(msg).jsonate())
            pipe.hset('ip_host', ip, dd['host_id'])
            
            pipe.execute()
            self.set_status(200)
            self.write('ok')
            
        except (ValueError, KeyError), e:
            self.set_status(400)
            self.write('ErrorCode 401')
            logger.error(u'上报的硬件信息格式错误' + str(e) + '\n' + traceback.format_exc())
            
        except RedisError, e:
            self.set_status(400)
            self.write('ErrorCode 501')
            logger.error(u'连接redis发生异常' + str(e) + '\n' + traceback.format_exc())
            
# 2. 处理上报的应用状态信息
class StatusHandler(tornado.web.RequestHandler):
    def initialize(self):
        # 显式使用连接池,阻塞式连接池
        # 注:socket_timeout　--创建socket，或者读写socket的超时
        # timeout    --从queue中取连接的超时
        pool = BlockingConnectionPool(max_connections=20, timeout=5, socket_timeout=5, \
            host=REDIS_HOST, port=REDIS_PORT, db=REDIS_DB_NUM, password=REDIS_PASSWORD)
        self.redis_db = redis.StrictRedis(connection_pool=pool)
        
    def post(self):
        logger = logging.getLogger("monitor.all")
        logger.info(u"接收到应用状态上报请求, 来源IP:%s, POST数据:%s",
            get_remote_ip(self.request), self.request.body)
        
        try:
            dd = json.loads(self.request.body)
            host = dd['host_id']
            # 针对每个应用分别处理
            for item in dd['app_list']:
                res = {}
                # 2) 提取上报的状态数据
                report = AppReport()
                report.app_name = item['appname']
                report.host = host
                for t in item['status']: 
                    report.data_dict[t['name']] = float(t['value'])
                
                logger.info(u"同批次中待处理的应用_主机:%s", unicode(report))
                
                res = deal_report(self, report)
                if res != 0:
                    self.set_status(400)
                    self.write('ErrorCode %s' % (res))
                    return None
                
            self.set_status(200)
            self.write('ok')

        except (ValueError, KeyError), e:
            self.set_status(400)
            self.write('ErrorCode 401')
            logger.error(u'上报的状态信息格式错误' + str(e) + '\n' + traceback.format_exc())
            
        except RedisError, e:
            self.set_status(400)
            self.write('ErrorCode 501')
            logger.error(u'连接redis发生异常' + str(e) + '\n' + traceback.format_exc())

# 每个请求中只包含一个应用的状态信息
class AppStatusHandler(tornado.web.RequestHandler):
    def initialize(self):
        # 显式使用连接池,阻塞式连接池
        # 注:socket_timeout　--创建socket，或者读写socket的超时
        # timeout    --从queue中取连接的超时
        pool = BlockingConnectionPool(max_connections=20, timeout=5, socket_timeout=5, \
            host=REDIS_HOST, port=REDIS_PORT, db=REDIS_DB_NUM, password=REDIS_PASSWORD)
        self.redis_db = redis.StrictRedis(connection_pool=pool)
        
    def post(self):
        logger = logging.getLogger("monitor.all")
        logger.info(u"接收到单个应用状态上报请求, 来源IP:%s, POST数据:%s",
            get_remote_ip(self.request), self.request.body)
        
        try:
            dd = json.loads(self.request.body)
            
            report = AppReport()
            report.app_name = dd['appname']
            if 'ip' in dd:
                report.host = str(self.redis_db.hget('ip_host', dd['ip']))
            else:
                report.host = dd['host_id']
            
            for t in dd['status']: 
                report.data_dict[t['name']] = float(t['value'])
            
            res = deal_report(self, report)
            if res == 0:
                self.set_status(200)
                self.write('ok')
            else:
                self.set_status(400)
                self.write('ErrorCode %s' % (res))

        except (ValueError, KeyError), e:
            self.set_status(400)
            self.write('ErrorCode 401')
            logger.error(u'上报的状态信息格式错误' + str(e) + '\n' + traceback.format_exc())
            
        except RedisError, e:
            self.set_status(400)
            self.write('ErrorCode 501')
            logger.error(u'连接redis发生异常' + str(e) + '\n' + traceback.format_exc())         

            
# 3. 提供check_app所需的监控数据
class MonitorHandler(tornado.web.RequestHandler):
    def initialize(self):
        # 显式使用连接池,阻塞式连接池
        # 注:socket_timeout　--创建socket，或者读写socket的超时
        # timeout    --从queue中取连接的超时
        pool = BlockingConnectionPool(max_connections=5, timeout=5, socket_timeout=5, \
            host=REDIS_HOST, port=REDIS_PORT, db=REDIS_DB_NUM, password=REDIS_PASSWORD)
        self.redis_db = redis.StrictRedis(connection_pool=pool)
        
    def get(self, appname, host):
        logger = logging.getLogger("monitor.all")
        logger.info(u"接收到应用监控请求, 来源IP:%s, 请求URL:%s",
            get_remote_ip(self.request), self.request.path)
            
        key = appname + '_' + host
        info  = self.redis_db.get(key)
        self.redis_db.delete(key)
        self.set_status(200)
        if info is None:
            info = ""
        self.write(info)

#计算监控项的值
#异常由上层函数处理
def compute_value(item, args):
    logger = logging.getLogger("monitor.all")
    if item['monitor_type'] == 1:
        return args[item['var_name'].strip()]
    else:
        res = 0
        formula = item['formula']
        patt = '\$(\w+)'
        v = re.search(patt, formula)
        while v is not None:
            formula = formula.replace(v.group(0), str(args[v.group(1)]))
            v = re.search(patt, formula)
        
        # 用于安全控制
        from math import acos, asin, atan, atan2, ceil, cos, cosh, degrees
        from math import e, exp, fabs, floor, fmod, frexp, hypot, ldexp, log
        from math import log10, modf, pi, pow, radians, sin, sinh, sqrt, tan, tanh
        
        #make a list of safe functions
        safe_list = ['acos', 'asin', 'atan', 'atan2', 'ceil', 'cos', 'cosh', 'degrees',\
            'e', 'exp', 'fabs', 'floor', 'fmod', 'frexp', 'hypot', 'ldexp', 'log', \
            'log10', 'modf', 'pi', 'pow', 'radians', 'sin', 'sinh', 'sqrt', 'tan', 'tanh']
        #use the list to filter the local namespace s
        safe_dict = dict([ (k, locals().get(k, None)) for k in safe_list ]) 
        res = eval(formula, {"__builtins__":None}, safe_dict)
        return res



# 获取应用对应的时间戳信息
class AppTimeStampHandler(tornado.web.RequestHandler):
    def initialize(self):
        # 显式使用连接池,阻塞式连接池
        # 注:socket_timeout　--创建socket，或者读写socket的超时
        # timeout    --从queue中取连接的超时
        pool = BlockingConnectionPool(max_connections=5, timeout=5, socket_timeout=5, \
            host=REDIS_HOST, port=REDIS_PORT, db=REDIS_DB_NUM, password=REDIS_PASSWORD)
        self.redis_db = redis.StrictRedis(connection_pool=pool)
        
    def post(self):
        logger = logging.getLogger("monitor.all")
        logger.info(u"接收到获取应用对应时间戳的请求信息, 来源IP:%s, POST数据:%s",
            get_remote_ip(self.request), self.request.body)
        
        try:
            dd = json.loads(self.request.body)
            monitor_type = dd['monitor_type']
            
            # 根据参数nocid_list和monitor_type获取相应机房下面指定类型的应用
            app_set = set()
            for nocid in dd['nocid_list']:
                hash_key = "noc_app_map_" + nocid
                item_list = self.redis_db.hget(hash_key, monitor_type)
                app_set = app_set | set(split_string(item_list))
                
                
            res_dd = {}
            # 从redis中获取当前monitor_type类型应用对应的时间戳信息
            hash_key = 'other_app_timestamp'
            
            # FIXME
            if monitor_type == 'http':
                hash_key = 'http_url_timestamp'
            elif monitor_type == 'ping':
                hash_key = 'ping_server_timestamp'
            elif monitor_type == 'tcp':
                hash_key = 'tcp_port_timestamp'
            
            app_timestamp_dict = self.redis_db.hgetall(hash_key)
            logger.debug(u"获取相应monitor_type类型应用对应的时间戳信息:%s", app_timestamp_dict)
            
            for key, value in app_timestamp_dict.iteritems():
                if key in app_set:
                    res_dd[key] = value
                    
            logger.debug(u"获取所配置的机房列表下面所属应用对应的时间戳信息:%s", res_dd)
            
            self.set_status(200)
            self.write(json.dumps(res_dd))
            
        except (ValueError, KeyError), e:
            self.set_status(401)
            self.write('ErrorCode 401')
            logger.error(u'请求数据格式错误' + str(e) + '\n' + traceback.format_exc())
            
        except RedisError, e:
            self.set_status(501)
            self.write('ErrorCode 501')
            logger.error(u'连接redis发生异常' + str(e) + '\n' + traceback.format_exc())
            

def createXml(appname, server_list, url_list):
    try:
        # 指定监控服务器的host和port
        host = HOST
        port = str(PORT)
        
        doc = minidom.Document()
        
        rootNode = doc.createElement("config")
        doc.appendChild(rootNode)
        
        node_appname = doc.createElement('appname')
        text_node_appname = doc.createTextNode(appname) #元素内容写入
        node_appname.appendChild(text_node_appname)
        rootNode.appendChild(node_appname)
        
        node_urlList = doc.createElement('urlList')
        
        for url_dict in url_list:
            node_url = doc.createElement('url')
            
            node_url_id = doc.createElement('url_id')
            text_node_url_id = doc.createTextNode(str(url_dict['url_id']))
            node_url_id.appendChild(text_node_url_id)
            node_url.appendChild(node_url_id)
            
            node_url_value = doc.createElement('url_value')
            text_node_url_value = doc.createTextNode(url_dict['url_value'])
            node_url_value.appendChild(text_node_url_value)
            node_url.appendChild(node_url_value)
            
            if url_dict.has_key('responsetime'):
                node_responsetime = doc.createElement('responsetime')
                text_node_responsetime = doc.createTextNode(str(url_dict['responsetime']))
                node_responsetime.appendChild(text_node_responsetime)
                node_url.appendChild(node_responsetime)
                
            if url_dict.has_key('type') and url_dict.has_key('target') and url_dict.has_key('value'):
                node_type = doc.createElement('type')
                text_node_type = doc.createTextNode(url_dict['type'])
                node_type.appendChild(text_node_type)
                node_url.appendChild(node_type)
                
                node_target = doc.createElement('target')
                text_node_target = doc.createTextNode(url_dict['target'])
                node_target.appendChild(text_node_target)
                node_url.appendChild(node_target)
                
                node_value = doc.createElement('value')
                text_node_value = doc.createTextNode(url_dict['value'])
                node_value.appendChild(text_node_value)
                node_url.appendChild(node_value)
            
            node_urlList.appendChild(node_url)
        
        rootNode.appendChild(node_urlList)
        
        node_monitor = doc.createElement('monitor')
        
        node_monitor_host = doc.createElement('host')
        text_node_monitor_host = doc.createTextNode(host)
        node_monitor_host.appendChild(text_node_monitor_host)
        node_monitor.appendChild(node_monitor_host)
        
        node_monitor_port = doc.createElement('port')
        text_node_monitor_port = doc.createTextNode(port)
        node_monitor_port.appendChild(text_node_monitor_port)
        node_monitor.appendChild(node_monitor_port)
        
        rootNode.appendChild(node_monitor)
        
        node_serverList = doc.createElement('serverList')
        for server in server_list:
            node_server = doc.createElement('server')
            text_node_server = doc.createTextNode(server)
            node_server.appendChild(text_node_server)
            node_serverList.appendChild(node_server)
        
        rootNode.appendChild(node_serverList)
        
        #xmlfile = doc.toxml("UTF-8")
        xmlfile_format = doc.toprettyxml(indent = "\t", newl="\n", encoding="UTF-8")
        return xmlfile_format
    
    except Exception, e:
        print e
    


# 获取应用对应的配置信息
class AppConfigHandler(tornado.web.RequestHandler):
    def initialize(self):
        # 显式使用连接池,阻塞式连接池
        # 注:socket_timeout　--创建socket，或者读写socket的超时
        # timeout    --从queue中取连接的超时
        pool = BlockingConnectionPool(max_connections=5, timeout=5, socket_timeout=5, \
            host=REDIS_HOST, port=REDIS_PORT, db=REDIS_DB_NUM, password=REDIS_PASSWORD)
        self.redis_db = redis.StrictRedis(connection_pool=pool)
        
    def post(self):
        logger = logging.getLogger("monitor.all")
        logger.info(u"接收到获取应用配置的请求信息, 来源IP:%s, POST数据:%s",
            get_remote_ip(self.request), self.request.body)
        
        try:
            dd = json.loads(self.request.body)
            nocid_list = dd['nocid_list']
            appname = dd['appname']
            
            try:
                # 从redis中获取当前应用对应的URL信息
                url_data = self.redis_db.hget('http_url_configuration', appname)
                url_list = json.loads(url_data)
                
                logger.debug(u"获取的url_list信息：")
                logger.debug(url_list)
            except Exception, e:
                self.set_status(401)
                self.write('ErrorCode 401')
                logger.error(u'当前应用没有URL配置信息:' + str(e) + '\n' + traceback.format_exc())
                return None
            
            # 从redis中获取当前应用对应的所有IP信息
            app_ip_data = self.redis_db.hget(appname + '_config', 'ip_list')
            app_ip_list = app_ip_data.split(',')
            
            try:
                # 从redis中获取当前配置机房列表对应的所有IP信息
                noc_ip_list = []
                for nocid in nocid_list:
                    noc_ip_data_tmp = self.redis_db.hget('noc_ip_map', nocid)
                    if noc_ip_data_tmp != None:
                        noc_ip_list_tmp = noc_ip_data_tmp.split(',')
                        for noc_ip_tmp in noc_ip_list_tmp:
                            if noc_ip_tmp not in noc_ip_list:
                                noc_ip_list.append(noc_ip_tmp)
            except Exception, e:
                self.set_status(401)
                self.write('ErrorCode 401')
                logger.error(u'解析机房对应IP信息出错:' + str(e) + '\n' + traceback.format_exc())
                return None
            
            # 计算该应用在当前机房的IP信息
            server_list = [ip for ip in app_ip_list if ip in noc_ip_list]
            
            logger.debug(u"获取的server_list信息：")
            logger.debug(server_list)
            
            
            xml_data = createXml(appname, server_list, url_list)
            
            
            logger.debug(u"生成的XML配置信息: ")
            logger.debug(xml_data)
            
            
            self.set_status(200)
            self.write(xml_data)
            
        except (ValueError, KeyError), e:
            self.set_status(401)
            self.write('ErrorCode 401')
            logger.error(u'请求数据格式错误' + str(e) + '\n' + traceback.format_exc())
            
        except RedisError, e:
            self.set_status(501)
            self.write('ErrorCode 501')
            logger.error(u'连接redis发生异常' + str(e) + '\n' + traceback.format_exc())
        

# 获取需要ping检查的ip列表
class PingIpListHandler(tornado.web.RequestHandler):
    def initialize(self):
        # 显式使用连接池,阻塞式连接池
        # 注:socket_timeout　--创建socket，或者读写socket的超时
        # timeout    --从queue中取连接的超时
        pool = BlockingConnectionPool(max_connections=5, timeout=5, socket_timeout=5, \
            host=REDIS_HOST, port=REDIS_PORT, db=REDIS_DB_NUM, password=REDIS_PASSWORD)
        self.redis_db = redis.StrictRedis(connection_pool=pool)
        
    def post(self):
        logger = logging.getLogger("monitor.all")
        logger.info(u"接收到获取需要ping检查的ip列表请求信息, 来源IP:%s, POST数据:%s",
            get_remote_ip(self.request), self.request.body)
        
        try:
            dd = json.loads(self.request.body)
            nocid_list = dd['nocid_list']
            appname = dd['appname']
            
            # 从redis中获取当前应用对应的所有IP信息
            app_ip_data = self.redis_db.hget(appname + '_config', 'ip_list')
            app_ip_set = set(split_string(app_ip_data))
            
            # 从redis中获取当前配置机房列表对应的所有IP信息
            ip_set = set()
            for nocid in nocid_list:
                noc_ip_set = set(split_string(self.redis_db.hget('noc_ip_map', nocid)))
                ip_set = ip_set | (app_ip_set & noc_ip_set)
                
            logger.debug(u"获取的ip_set信息：%s", ip_set)
            
            data = create_ping_xml(ip_set)
            
            self.set_status(200)
            self.write(data)
            
        except (ValueError, KeyError), e:
            self.set_status(401)
            self.write('ErrorCode 401')
            logger.error(u'请求数据格式错误' + str(e) + '\n' + traceback.format_exc())
            
        except RedisError, e:
            self.set_status(501)
            self.write('ErrorCode 501')
            logger.error(u'连接redis发生异常' + str(e) + '\n' + traceback.format_exc())

# 创建TCP 监控需要的xml文件
def create_tcp_xml(ip_list, port_list):
    doc = minidom.Document()
    
    rootNode = doc.createElement("config")
    doc.appendChild(rootNode)
    
    # 1. ip_list
    node_ip_list = doc.createElement('ip_list')
    for ip in ip_list:
        node_ip = doc.createElement('ip')
        text_node_ip = doc.createTextNode(ip) #元素内容写入
        node_ip.appendChild(text_node_ip)
        node_ip_list.appendChild(node_ip)
     
    rootNode.appendChild(node_ip_list)
        
    # 2. port_list
    node_port_list = doc.createElement('port_list')
    # port_item is dict
    for port_item in port_list:
        node_port = doc.createElement('port')
        # 必须包含 "port" 这个key
        text_node_port = doc.createTextNode(port_item['port']) 
        node_port.appendChild(text_node_port)
        node_port_list.appendChild(node_port)
        
    rootNode.appendChild(node_port_list)
    return doc.toxml()

# 创建Ping 监控需要的xml文件   
def create_ping_xml(ip_list):
    doc = minidom.Document()
    
    rootNode = doc.createElement("config")
    doc.appendChild(rootNode)
    
    # ip_list
    node_ip_list = doc.createElement('ip_list')
    for ip in ip_list:
        node_ip = doc.createElement('ip')
        text_node_ip = doc.createTextNode(ip) #元素内容写入
        node_ip.appendChild(text_node_ip)
        node_ip_list.appendChild(node_ip)
    rootNode.appendChild(node_ip_list)
    return doc.toxml()
    
# 获取tcp应用的server_list和port_list
class TcpConfigHandler(tornado.web.RequestHandler):
    def initialize(self):
        # 显式使用连接池,阻塞式连接池
        # 注:socket_timeout　--创建socket，或者读写socket的超时
        # timeout    --从queue中取连接的超时
        pool = BlockingConnectionPool(max_connections=5, timeout=5, socket_timeout=5, \
            host=REDIS_HOST, port=REDIS_PORT, db=REDIS_DB_NUM, password=REDIS_PASSWORD)
        self.redis_db = redis.StrictRedis(connection_pool=pool)
        
    def post(self):
        logger = logging.getLogger("monitor.all")
        logger.info(u"接收到获取需要tcp检查的应用的配置信息, 来源IP:%s, POST数据:%s",
            get_remote_ip(self.request), self.request.body)
        
        try:
            dd = json.loads(self.request.body)
            nocid_list = dd['nocid_list']
            appname = dd['appname']
            
            # 1. IP信息
            # 从redis中获取当前应用对应的所有IP信息
            app_ip_data = self.redis_db.hget(appname + '_config', 'ip_list')
            app_ip_set = set(split_string(app_ip_data))
            
            # 从redis中获取当前配置机房列表对应的所有IP信息
            ip_set = set()
            for nocid in nocid_list:
                noc_ip_set = set(split_string(self.redis_db.hget('noc_ip_map', nocid)))
                ip_set = ip_set | (app_ip_set & noc_ip_set)
                
            logger.debug(u"获取的ip_set信息：%s", ip_set)
            
            # 2. 应用对应的端口信息
            port_info = self.redis_db.hget('tcp_port_configuration', appname)
            logger.debug(u"获取的端口配置信息：%s", port_info)
            
            res = create_tcp_xml(list(ip_set), json.loads(port_info))
            
            self.set_status(200)
            self.write(res)
            
        except (ValueError, KeyError), e:
            self.set_status(401)
            self.write('ErrorCode 401')
            logger.error(u'请求数据格式错误' + str(e) + '\n' + traceback.format_exc())
            
        except RedisError, e:
            self.set_status(501)
            self.write('ErrorCode 501')
            logger.error(u'连接redis发生异常' + str(e) + '\n' + traceback.format_exc())

       
application = tornado.web.Application([
    (r"/hardware", HardwareHandler),
    (r"/status", StatusHandler),
    # 新接口供外部系统使用提交应用的状态信息
    (r"/app_status", AppStatusHandler),
    
    # 为url主动监控提供的接口
    (r"/getAppTimeStamp", AppTimeStampHandler),
    # FIXME 命名有问题
    (r"/getAppConfig", AppConfigHandler),
    # 为ping主动监控提供的接口
    (r"/getPingIpList", PingIpListHandler),
    # 为tcp主动监控提供的接口
    (r"/getTcpConfig", TcpConfigHandler),
    # 供check_app获取某个应用在某个主机上的状态
    (r"/monitor/([\w%]+)/(\w+)", MonitorHandler),

])

if __name__ == "__main__":
    #初始化 日志记录器
    initlog('monitor.all', LOG_HOST, LOG_PORT)
    
    logger = logging.getLogger('monitor.all')
    logger.info('kalmaegi server start.')
    
    if len(sys.argv) == 2:
        try:
            PORT = int(sys.argv[1])
            logger.info('venus 使用端口 %s 启动。', PORT)
            print 'venus 使用端口 %s 启动。' %  PORT
        except BaseException, e:
            logger.info('kalmaegi 使用配置文件中指定的默认端口 %s 启动。', PORT)
            print 'kalmaegi 使用配置文件中指定的默认端口 %s 启动。' % PORT
    else:
        
        logger.info('kalmaegi 使用配置文件中指定的默认端口 %s 启动。', PORT)
        print 'kalmaegi 使用配置文件中指定的默认端口 %s 启动。' % PORT
        
    application.listen(PORT)
    tornado.ioloop.IOLoop.instance().start()
    
    
    
