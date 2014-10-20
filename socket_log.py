# -*- coding:utf-8 -*-                                                                                                                                                                                                                          
import logging
import logging, logging.handlers
from logging.handlers import SocketHandler

# 直接通过socket将日志传输到日志服务器
def initlog(logger_name, host, port, logLevel=logging.INFO):
    if logger_name not in logging.Logger.manager.loggerDict:
        logger = logging.getLogger(logger_name)
        handler = SocketHandler(host, port)
        handler.setLevel(logLevel)
        logger.addHandler(handler)
        logger.setLevel(logLevel)
    return logging.getLogger(logger_name)

