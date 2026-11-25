#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""从个人飞书招聘表导出网站数据。"""
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
    'jobs': {'table_id': os.environ.get('JOBS_TABLE_ID') or 'tbl3VaUp39mxFa44', 'fields': ['公司名称','行业大类','企业性质','工作地点','官方公告','更新时间','招聘岗位','截止时间','是否需要笔试','投递方式','备注/提示','招聘对象','批次','工作地点文本']},
    'majors': {'table_id': os.environ.get('MAJORS_TABLE_ID', ''), 'fields': ['专业名称','适合的岗位和公司','了解']},
    'platforms': {'table_id': os.environ.get('PLATFORMS_TABLE_ID', ''), 'fields': ['官方平台','央企','地方社保局','综合平台','其他央企']},
    'resources': {'table_id': os.environ.get('RESOURCES_TABLE_ID', ''), 'fields': ['资料名称','详情']}
}
ARRAY_FIELDS = {'行业大类','企业性质','工作地点','是否需要笔试','招聘对象','批次'}

def get_tenant_access_token():
    response = requests.post('https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal', json={'app_id': APP_ID, 'app_secret': APP_SECRET}, timeout=30)
    response.raise_for_status()
    result = response.json()
    if result.get('code') != 0:
        raise RuntimeError(f'获取token失败: {result}')
    return result['tenant_access_token']

def get_table_records(token, table_id, page_size=200):
    records, page_token = [], None
    while True:
        params = {'page_size': page_size}
        if page_token:
            params['page_token'] = page_token
        response = requests.get(f'https://open.feishu.cn/open-apis/bitable/v1/apps/{BASE_TOKEN}/tables/{table_id}/records', headers={'Authorization': f'Bearer {token}'}, params=params, timeout=30)
        response.raise_for_status()
        result = response.json()
        if result.get('code') != 0:
            raise RuntimeError(f'获取记录失败: {result}')
        data = result.get('data', {})
        records.extend(data.get('items', []))
        if not data.get('has_more'):
            return records
        page_token = data['page_token']
        time.sleep(0.1)

def extract_field_value(value):
    if value is None:
        return ''
    if isinstance(value, list):
        return [extract_field_value(item) for item in value]
    if isinstance(value, dict):
        return value.get('text', value.get('link', value.get('name', str(value))))
    return str(value)

def records_to_objects(records, fields):
    objects = []
    for record in records:
        obj = {}
        for name in fields:
            value = record.get('fields', {}).get(name)
            if name in ('更新时间','截止时间') and isinstance(value, (int,float)):
                value = datetime.fromtimestamp(value / 1000, timezone(timedelta(hours=8))).strftime('%Y/%m/%d')
            value = extract_field_value(value)
            if '公司名称' in fields:
                if name in ARRAY_FIELDS:
                    value = [str(v) for v in value if v] if isinstance(value,list) else ([value] if value else [])
                elif isinstance(value,list):
                    value = ''.join(str(v) for v in value)
            obj[name] = value
        if '公司名称' not in fields or str(obj.get('公司名称','')).strip():
            objects.append(obj)
    return objects


def fetch_public_jobs():
    response = requests.get('https://api.github.com/repos/HU-eun/campus-recruitment/commits/main', timeout=60)
    response.raise_for_status()
    sha = response.json()['sha']
    root = f'https://raw.githubusercontent.com/HU-eun/campus-recruitment/{sha}/data/'
    response = requests.get(root + 'jobs.json', timeout=120)
    response.raise_for_status()
    rows = response.json()
    if not isinstance(rows,list) or len(rows) < 1000 or not all(isinstance(row,dict) for row in rows):
        raise ValueError('公开招聘源异常，停止发布并保留现有数据')
    response = requests.get(root + 'summary.json', timeout=60)
    response.raise_for_status()
    source_summary = response.json()
    if source_summary.get('jobs_count') != len(rows):
        raise ValueError('公开源统计与数据不一致，停止发布')
    return rows, {'repository': 'HU-eun/campus-recruitment', 'commit': sha, 'update_time': source_summary.get('update_time'), 'raw_count': len(rows)}

def merge_jobs(public_rows, personal_rows):
    merged = {}
    for source, rows in [('原项目公开招聘数据',public_rows),('个人飞书补充',personal_rows)]:
        normalized = records_to_objects([{'fields':row} for row in rows], TABLES['jobs']['fields'])
        for row in normalized:
            company = row['公司名称'].strip()
            if company.startswith('【同步测试】') or '筛选前必看' in company:
                continue
            if '这是同步测试，不是真实招聘岗位' in row['招聘岗位']:
                continue
            key = json.dumps([row.get(field) for field in ('公司名称','招聘岗位','官方公告','截止时间','批次','招聘对象')], ensure_ascii=False, sort_keys=True)
            row['_数据来源'] = source
            merged[key] = row
    jobs = list(merged.values())
    if len(jobs) < 1000:
        raise ValueError('合并后岗位数量异常，停止发布')
    return jobs

def main():
    public_rows, public_source = fetch_public_jobs()
    token = get_tenant_access_token()
    os.makedirs('data', exist_ok=True)
    all_data = {}
    for key, config in TABLES.items():
        if not config['table_id']:
            with open(f'data/{key}.json', encoding='utf-8') as f:
                all_data[key] = json.load(f)
            continue
        objects = records_to_objects(get_table_records(token, config['table_id']), config['fields'])
        all_data[key] = objects
    all_data['jobs'] = merge_jobs(public_rows, all_data['jobs'])
    for key, objects in all_data.items():
        with open(f'data/{key}.json', 'w', encoding='utf-8') as f:
            json.dump(objects, f, ensure_ascii=False, indent=2)
    with open('data/all-data.js', 'w', encoding='utf-8') as f:
        for key, objects in all_data.items():
            f.write(f'window.{key}Data = ')
            json.dump(objects, f, ensure_ascii=False)
            f.write(';\n')
    summary = {f'{key}_count': len(value) for key,value in all_data.items()}
    summary['public_source'] = public_source
    summary['update_time'] = datetime.now(timezone(timedelta(hours=8))).strftime('%Y-%m-%d %H:%M:%S')
    with open('data/summary.json','w',encoding='utf-8') as f:
        json.dump(summary,f,ensure_ascii=False,indent=2)
    print(f'导出完成: {summary}')

if __name__ == '__main__':
    main()
