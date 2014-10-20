# -*- coding:utf-8 -*-
import httplib
import urllib
import random
import time
import json

def main():
#    headers = {'X-Forwarded-For':'222.222.222.222'}
#    dd = {'name':'test', 'password':'test', 'sender':'15313352375', 'template_id':22, 'tp_var1':'中文', 'tp_var2':'abc','mobiles':'18618259692,15313352375'}
#    msg_body = urllib.urlencode(dd)
#    #headers = {"Content-Type":"application/x-www-form-urlencoded"}
#    headers = {"Content-Type":"text/plain"}
    headers = {}
    msg_body = '{"host_id": "GD3160186877","appname": "HOST_STATUS", "status": [{"name": "CPU_LOAD1", "value": "2.3"}, {"name": "CPU_LOAD5", "value": "2.1"}, {"name": "CPU_LOAD15", "value": "3.0"}, {"name": "SYS_MEM", "value": "90.2"}, {"name": "SYS_CPU", "value":"87.5"}] }'
    dd = json.loads(msg_body)
    print dd
    print '--------------------'
    print msg_body
    conn = httplib.HTTPConnection("localhost",8022)
    conn.request("POST", "/app_status", msg_body, headers)
    response = conn.getresponse()
    print response.status
    print type(response.status)
    print response.reason
    data = response.read()
    print 'response.read(): ', type(data), data
    conn.close()
    print 'ok'

#------------------------- start---------------------------
if __name__ == '__main__':
    main()


