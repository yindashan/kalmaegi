#!/bin/bash
# 如果需要修改启动的端口号修改PORTS即可,如果由多个，用半角逗号分隔
PORTS="9101,9102"
PATH=`dirname $0`

Start(){
	arr=(${PORTS//,/ })

	for i in ${arr[@]}
	do
	    /usr/bin/nohup /usr/bin/python $PATH/kalmaegi.py $i  > /dev/null  &
	done
	
}

Start
