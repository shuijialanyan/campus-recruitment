#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""飞书多维表格数据导出脚本"""

import os
import json
import time
from datetime import datetime, timezone, timedelta
import requests

APP_ID = os.environ.get('LARK_APP_ID', '')
APP_SECRET = os.environ.get('LARK_APP_SECRET', '')
BASE_TOKEN = os.environ.get('BASE_TOKEN', '')
if not all([APP_ID, APP_SECRET, BASE_TOKEN]):
    raise SystemExit('请配置 LARK_APP_ID、LARK_APP_SECRET、BASE_TOKEN')

TABLES = {
    'jobs': {
        'table_id': os.environ.get('JOBS_TABLE_ID') or 'tbl3VaUp39mxFa44',
        'fields': ['公司名称', '行业大类', '企业性质', '工作地点', '官方公告', '更新时间',
                   '招聘岗位', '截止时间', '是否需要笔试', '投递方式', '备注/提示',
                   '招聘对象', '批次', '工作地点文本']
    },
    'majors': {
        'table_id': os.environ.get('MAJORS_TABLE_ID', ''),
        'fields': ['专业名称', '适合的岗位和公司', '了解']
    },
    'platforms': {
        'table_id': os.environ.get('PLATFORMS_TABLE_ID', ''),
        'fields': ['官方平台', '央企', '地方社保局', '综合平台', '其他央企']
    },
    'resources': {
        'table_id': os.environ.get('RESOURCES_TABLE_ID', ''),
        'fields': ['资料名称', '详情']
    }
}

def get_tenant_access_token():
    url = 'https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal'
    response = requests.post(url, json={'app_id': APP_ID, 'app_secret': APP_SECRET}, timeout=30)
    response.raise_for_status()
    result = response.json()
    if result.get('code') == 0:
        return result.get('tenant_access_token')
    raise RuntimeError(f'获取token失败: {result}')

def get_table_records(token, table_id, page_size=200):
    records = []
    page_token = None
    while True:
        url = f'https://open.feishu.cn/open-apis/bitable/v1/apps/{BASE_TOKEN}/tables/{table_id}/records'
        headers = {'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'}
        params = {'page_size': page_size}
        if page_token:
            params['page_token'] = page_token
        response = requests.get(url, headers=headers, params=params, timeout=30)
        response.raise_for_status()
        result = response.json()
        if result.get('code') != 0:
            raise RuntimeError(f'获取记录失败: {result}')
        data = result.get('data', {})
        records.extend(data.get('items', []))
        if not data.get('has_more'):
            break
        page_token = data.get('page_token')
        time.sleep(0.1)
    return records

def extract_field_value(value):
    if value is None:
        return ''
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return [extract_field_value(item) for item in value]
    if isinstance(value, dict):
        return value.get('text', value.get('link', value.get('name', str(value))))
    return str(value)

def records_to_objects(records, fields):
    objects = []
    for record in records:
        obj = {}
        for field_name in fields:
            value = record.get('fields', {}).get(field_name)
            if field_name in ('更新时间', '截止时间') and isinstance(value, (int, float)):
                value = datetime.fromtimestamp(value / 1000, timezone(timedelta(hours=8))).strftime('%Y/%m/%d')
            obj[field_name] = extract_field_value(value)
        objects.append(obj)
    return objects

def main():
    print('正在获取飞书访问令牌...')
    token = get_tenant_access_token()
    os.makedirs('data', exist_ok=True)
    all_data = {}
    for key, config in TABLES.items():
        if not config['table_id']:
            with open(f'data/{key}.json', encoding='utf-8') as f:
                all_data[key] = json.load(f)
            continue
        print(f'正在导出 {key}...')
        records = get_table_records(token, config['table_id'])
        objects = records_to_objects(records, config['fields'])
        if key == 'jobs' and (not objects or not any(row.get('公司名称') for row in objects)):
            raise ValueError('招聘表为空或缺少公司名称字段；停止更新，保留现有数据')
        all_data[key] = objects
    # 所有读取成功后才写入，避免失败时覆盖现有数据。
    for key, objects in all_data.items():
        with open(f'data/{key}.json', 'w', encoding='utf-8') as f:
            json.dump(objects, f, ensure_ascii=False, indent=2)
    with open('data/all-data.js', 'w', encoding='utf-8') as f:
        for key in ['jobs', 'majors', 'platforms', 'resources']:
            f.write(f'window.{key}Data = ')
            json.dump(all_data[key], f, ensure_ascii=False)
            f.write(';\n')
    summary = {f'{key}_count': len(value) for key, value in all_data.items()}
    summary['update_time'] = datetime.now(timezone(timedelta(hours=8))).strftime('%Y-%m-%d %H:%M:%S')
    with open('data/summary.json', 'w', encoding='utf-8') as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    print(f'导出完成: {summary}')

if __name__ == '__main__':
    main()
