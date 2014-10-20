# -*- coding:utf-8 -*-
import httplib
import urllib
import random
import time
import json
# http://localhost:8080/monitoritem/fetch_data/?point_data_id=15&start=2014-02-15%2000%3A00%3A00&end=2014-02-16%2000%3A00%3A00
def main():
    headers = {}
    dd = {'point_data_id':15, 'start':'2014-02-15 00:00:00', 'end':'2014-02-16 00:00:00' }
    params = json.dumps(dd)

    conn = httplib.HTTPConnection("10.2.161.15",8091)
    conn.request("GET", "/monitoritem/fetch_data", params, headers)
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


