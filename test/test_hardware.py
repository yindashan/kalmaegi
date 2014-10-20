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
    msg_body = '{"hardware": [{"name": "IP", "value": "192.168.1.101"}, {"name": "MEM_TOTAL", "value": "1024"}, {"name": "CPU_COUNT", "value": "2"}, {"name": "DETAIL", "value": "abcxxxx"}], "host_id": "GD9790186807"}'
    dd = json.loads(msg_body)
    print dd
    print '--------------------'
    print msg_body
    conn = httplib.HTTPConnection("localhost",8080)
    conn.request("POST", "/hardware", msg_body, headers)
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


