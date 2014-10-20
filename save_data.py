#!/usr/bin/python
# -*- coding:utf-8 -*-
import time
import json

class PointData(object):
    def __init__(self, point_id, time, value, step):
        self.point_id = point_id
        self.time = time
        self.value = value
        self.step = step
        
    def jsonate(self):
        dd = {}
        dd['point_id'] = self.point_id
        # 转换成字符串
        dd['time'] = time.strftime('%Y-%m-%d %H:%M:%S',time.localtime(self.time))
        dd['value'] = self.value
        dd['step'] = self.step
        return json.dumps(dd)
        
# 平均值的方式生成聚合点    
def cdp(item_list, point_id, curr_time, next_step):
    value = 0.0
    for item in item_list:
        dd = json.loads(item)
        value += dd['value']
    if item_list:
        value = value/len(item_list)
    return  PointData(point_id, curr_time, value, next_step)

# 存储监控点数据
def save_point_data(handler, dd):
    # ------------ 初始化 ---------
    appname = dd['appname']
    host = dd['host']
    mid_value_dict = {}
    for item in dd['monitor']:
        mid_value_dict[item['id']] = item['value']
        
    # --------------------------
    pipe = handler.redis_db.pipeline()
    # 获取该应用的步长设置
    step_str = handler.redis_db.hget(appname + '_config', "storage_step")
    if step_str is None:
        step_str = '1,5,30,360'
        
    step_list = [ int(item) for item  in step_str.split(',')]
    step_list.insert(0, 0)
    
    # 注: step=0 为主记录点, 其它为聚合点
    curr_time = time.time()
    
    # ------------------------------------------------------
    # 把所有需要的东西提前批量获取
    buffer_dict = {}
    point_id_list = []
    # 1. --------------------
    for mid in mid_value_dict:
        field = '%s_%s_%s' % (appname, host, mid)
        pipe.hget('monitor_point', field)
        
    res_list = pipe.execute()
    i = 0
    for mid in mid_value_dict:
        field = '%s_%s_%s' % (appname, host, mid)
        buffer_dict[field] = res_list[i]
        point_id_list.append(res_list[i])
        i =  i + 1
        
    # 2. --------------------        
    for point_id in point_id_list:
        for step in step_list:
            st_key = 'mp_%s_%s_starttime' % (point_id, step)
            pipe.get(st_key)
    res_list = pipe.execute()
    
    i  = 0
    for point_id in point_id_list:
        for step in step_list:
            st_key = 'mp_%s_%s_starttime' % (point_id, step)
            buffer_dict[st_key] = res_list[i]
            i = i + 1
    
    # 3. --------------------
    for point_id in point_id_list:
        for step in step_list:
            list_key = 'mp_%s_%s_list' % (point_id, step)
            pipe.lrange(list_key, 0, -1)
    res_list = pipe.execute()
    
    i  = 0
    for point_id in point_id_list:
        for step in step_list:
            list_key = 'mp_%s_%s_list' % (point_id, step)
            buffer_dict[list_key] = res_list[i]
            i = i + 1
    
    # -----------------------------------------------------
    
    # 延迟执行
    delay_push = []
    for mid in mid_value_dict:
        # 2. 通过应用名称-主机-监控项ID获取监控点ID
        point_id = buffer_dict['%s_%s_%s' % (appname, host, mid)]
        if point_id is None:
            point_id = -1
        else:
            point_id = int(point_id)
        
        for i in range(len(step_list)):
            step = step_list[i]
            # 一个不存在step
            next_step = 1000
            if i < len(step_list) - 1:
                next_step = step_list[i + 1]
                
            # 获取开始时间
            st_key = 'mp_%s_%s_starttime' % (point_id, step)
            list_key = 'mp_%s_%s_list' % (point_id, step)
            
            # start_time = redis_db.get(st_key)
            start_time = buffer_dict[st_key]
            if start_time is None:
                pipe.set(st_key, str(curr_time))
                start_time = curr_time
            
            start_time = float(start_time)
            
            
            if (curr_time - start_time) >= next_step * 60:
                # 1) 生成新的聚合点, 插入下一个步长的队列(延迟执行), 同时推入"point_data" 队列
                # item_list = redis_db.lrange(list_key, 0, -1)
                item_list = buffer_dict[list_key]
                p = cdp(item_list, point_id, curr_time, next_step)
                delay_push.append(p)
                
                # 2) 清空原步长队列
                pipe.delete(list_key)
                
                # 3) 重设开始时间
                pipe.set(st_key, str(curr_time))
                
            # 如果是第一个步长，还要插入一条主记录
            if i == 0:
                delay_push.append(PointData(point_id, curr_time, mid_value_dict[mid], step))
    
    for point in delay_push:
        if point.step in step_list:
            pipe.rpush("point_data", point.jsonate())
            if point.step != step_list[ len(step_list) -1 ]:
                pipe.rpush('mp_%s_%s_list' % (point.point_id, point.step), point.jsonate())
            
    
    pipe.execute()
    
    
    
    
    
    