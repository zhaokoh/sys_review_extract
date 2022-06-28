#!/usr/bin/env python3
import configparser
import glob
import html
import json
import logging
import math
import os
import re
import shutil
import socket
import sys
import uuid
import xml.etree.ElementTree as ET
from datetime import datetime
from difflib import SequenceMatcher
from os import listdir
from os.path import isfile, join
from re import S

import pandas as pd
from flask import Flask, jsonify, redirect, render_template, request
from fuzzywuzzy import process
from jinja2 import Template
from lxml import etree
from lxml.etree import tostring
from pybliometrics.scopus import ScopusSearch
from pybliometrics.scopus.utils import config
from sqlalchemy import (Column, Date, DateTime, Float, Integer, MetaData,
                        String, Table, and_, create_engine, or_)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from sqlalchemy.sql import func

template_dir = os.path.abspath('templates/system_review')
static_dir = os.path.abspath('images')
app = Flask(__name__, template_folder=template_dir, static_folder=static_dir)

app_config = configparser.ConfigParser()
app_config._interpolation = configparser.ExtendedInterpolation()
app_config.read_file(open('./app.cfg'))

repository_path = app_config['global']['repository.path']
db_view_scopus = "vw_fts_master_working"
db_table_extract = "fts_extract"
db_table_instr_extract = "fts_instrument_extract"

def empty_str_if_none(raw):
    if raw is None:
        return ""
    else:
        return raw

def to_count(raw):
    if raw is None:
        return 0
    else:
        return int(round(float(raw)))

def to_author(author_raw):
    if author_raw is None:
        return ""
    else:
        author_raw = eval(author_raw)
        return "; ".join([x['formatted'] for x in author_raw])

def to_year(raw):
    if raw is None:
        return ""
    else:
        raw = eval(raw)
        if 'year' in raw.keys():
            return raw['year']        
        else:
            return ""

def to_url(url_raw):
    if url_raw is None:
        return ""
    else:
        url_raw = eval(url_raw)
        if len(url_raw) > 0:
            return url_raw[0]
        else:
            return ""
            
def to_ppid(raw, attachments):
    if raw is None:
        if attachments is None:
            return ""
        else:
            attach_list = eval(attachments)
            if len(attach_list) > 0:
                return attach_list[0]['pub_id']
            else:
                return ""
    else:
        return raw

def to_str_join_list(raw):
    if raw is None:
        return ""
    else:
        raw = eval(raw)
        return ", ".join(raw)

def to_ppStatus(labels, folders, starred):
    status = []
    if starred is not None and starred == "1.0":
        status = status + ['⭐ ']

    if labels is not None:
        status = status + eval(labels)

    if folders is not None:
        status = status + eval(folders)

    return ", ".join(status)

def format_id(row):
    return '<a href="/scopus-item/extract/%s">%s</a>' % (empty_str_if_none(row["id"]), empty_str_if_none(row["id"]))
    #return row["id"]

def format_extract(row, key):
    completed = ''
    if empty_str_if_none(row["extract_id"]) != "":
        completed = "✅"

    return '<a href="/scopus-item/extract/%s">%s %s</a>' % (empty_str_if_none(row[key]), 'Extract', completed)

def format_doi(row):
    return ('<a target="_blank" href="https://doi.org/%s">' % (empty_str_if_none(row["doi"]))) + empty_str_if_none(row['doi']) + "</a>"

def format_abstract(row, key):
    return ('<div id="abs-%s" style="display: none;">' % (row[key])) + empty_str_if_none(row['abstract']) + ('</div><a href="javascript:show_abs(%s, ''%s'');">Show</a>' % ("'" + row[key] + "'", "'" + row["title"] + "'"))

def format_description(row, key):
    return ('<div id="abs-%s" style="display: none;">' % (row[key])) + empty_str_if_none(row['description']) + ('</div><a href="javascript:show_abs(%s, ''%s'');">Show</a>' % ("'" + row[key] + "'", "'" + row["title"] + "'"))

def format_decision(row):
    decision = empty_str_if_none(row['decision'])
    return decision

def format_status(row):
    status = empty_str_if_none(row['status'])
    return status

def process_wos_df(df):
    #df['title'] = df.apply(lambda row : format_title(row), axis = 1)
    df['doi'] = df.apply(lambda row : format_doi(row), axis = 1)
    df['abstract'] = df.apply(lambda row : format_abstract(row, "ID"), axis = 1)

    # df['author'] = df['author'].apply(to_author)
    # df['url'] = df['url'].apply(to_url)
    # df['year'] = df['published'].apply(to_year)
    # df['ppStatus'] = df.apply(lambda x: to_ppStatus(x['labelsNamed'], x['foldersNamed'], x['starred']), axis=1)
    # df['gs_cited_by_count'] = df['gs_cited_by_count'].apply(to_count)
    # df['_id'] = df.apply(lambda x: to_ppid(x['_id'], x['attachments']), axis=1)

    return df

def process_scopus_df(df):
    #df['title'] = df.apply(lambda row : format_title(row), axis = 1)

    # This has to be done first because it needs to use the original eid
    # df['description'] = df.apply(lambda row : format_description(row, "id"), axis = 1)

    if not df.empty:
        df['extract'] = df.apply(lambda row: format_extract(row, "id"), axis = 1)
    
    df['id'] = df.apply(lambda row : format_id(row), axis = 1)
    df['doi'] = df.apply(lambda row : format_doi(row), axis = 1)
    df['status'] = df.apply(lambda row: format_status(row), axis = 1)

    # df['author'] = df['author'].apply(to_author)
    # df['url'] = df['url'].apply(to_url)
    # df['year'] = df['published'].apply(to_year)
    # df['ppStatus'] = df.apply(lambda x: to_ppStatus(x['labelsNamed'], x['foldersNamed'], x['starred']), axis=1)
    # df['gs_cited_by_count'] = df['gs_cited_by_count'].apply(to_count)
    # df['_id'] = df.apply(lambda x: to_ppid(x['_id'], x['attachments']), axis=1)

    return df

def process_one_scopus(df):
    #df['title'] = df.apply(lambda row : format_title(row), axis = 1)
    df['raw_doi'] = df['doi']
    df['doi'] = df.apply(lambda row : format_doi(row), axis = 1)
    df['status'] = df.apply(lambda row: format_status(row), axis = 1)
    df['description'] = ""
    return df

@app.route("/wos-query")
def wos_query():
    return render_template('wos_query_result.html')

@app.route("/save-query")
def save_query():
    return render_template('save_list.html')

@app.route("/scopus-query")
def scopus_query():
    return render_template('scopus_query_result.html')    
            
@app.route("/scopus-query-pass")
def scopus_query_pass():
    return render_template('scopus_query_result_pass.html')    

@app.route("/scopus-query-pass-sysreview")
def scopus_query_pass_sysreview():
    return render_template('scopus_query_result_pass_sysreview.html')

@app.route("/custom_paper_entry")
def custom_paper_entry():
    return render_template("scopus_custom_paper_entry.html", article = {})

@app.route("/home-summary")
def home_summary():
    session = None
    try:
        engine = create_engine('sqlite:///' + repository_path)  

        Session = sessionmaker(bind = engine)
        session = Session()

        total_result = engine.scalar("select count(*) from %s" % db_view_scopus)
        total_reject = engine.scalar("select count(*) from %s where decision == 'Reject'" % db_view_scopus)
        total_reject_second = engine.scalar("select count(*) from %s where decision == 'Reject-Second'" % db_view_scopus)
        total_pass = engine.scalar("select count(*) from %s where decision == 'Pass'" % db_view_scopus)
        total_maybe = engine.scalar("select count(*) from %s where decision == 'Maybe'" % db_view_scopus)
        total_save = engine.scalar("select count(*) from %s where status == 'SAVE'" % db_view_scopus)

        q = {}
        q['recordsTotal'] = total_result
        q['recordsPass'] = total_pass
        q['recordsReject'] = total_reject
        q['recordsRejectSecond'] = total_reject_second
        q['recordsMaybe'] = total_maybe
        q['recordsSave'] = total_save
        q['recordsOutstanding'] = total_result - total_pass - total_reject - total_reject_second - total_maybe

        return json.dumps(q, ensure_ascii=True)
    except:
        print("Unexpected error:", sys.exc_info()[0])
        raise
    finally:
        if session is not None:
            session.close()   

@app.route("/scopus-query-data")
def scopus_queries_data():
    return _scopus_query_data()

@app.route("/scopus-query-data-pass")
def scopus_queries_data_pass():
    return _scopus_query_data(include_decisions=['Pass'], xtra_criteria=["extract_id is null"])

@app.route("/query-save")
def query_save():
    return _scopus_query_data(xtra_criteria=["status = 'SAVE'"])

@app.route("/scopus-query-data-pass-review")
def scopus_queries_data_pass_review():
    return _scopus_query_data(include_decisions=['Pass'], xtra_criteria=["lower(title) like '%review%'", "extract_id is null"])

@app.route("/query-relevant-papers-data")
def query_relevant_papers_data():
    session = None
    try:
        engine = create_engine('sqlite:///' + repository_path)  

        Session = sessionmaker(bind = engine)
        session = Session()

        sql = ("select id, title, published_year, doi from %s where parent_paper_id = '%s'" % ("sr_custom_paper", request.args.get('parentPaperId')))

        df = pd.read_sql(sql, con=engine)
        recordsFiltered = len(df)

        if recordsFiltered > 0:
            df['id'] = df.apply(lambda row : format_id(row), axis = 1)
            df['doi'] = df.apply(lambda row : format_doi(row), axis = 1)

        l = [dict(v) for _, v in df.iterrows()]

        q = {}
        q['data'] = l
        q['recordsTotal'] = recordsFiltered
        q['recordsFiltered'] = recordsFiltered

        return json.dumps(q, ensure_ascii=True)
    except:
        print("Unexpected error:", sys.exc_info()[0])
        raise
    finally:
        if session is not None:
            session.close()         


@app.route("/query-instrument-names")
def query_instrument_names():
    session = None
    search_term = request.args.get("term")

    try:
        engine = create_engine('sqlite:///' + repository_path)  

        Session = sessionmaker(bind = engine)
        session = Session()

        sql = ("select distinct instrument_name from (select instrument_name from sr_instrument_extract union \
                select instrument_name from fts_instrument_extract \
                ) where lower(instrument_name) like '%" + search_term.lower() + "%' order by instrument_name")

        df = pd.read_sql(sql, con=engine)
        return json.dumps(df["instrument_name"].tolist(), ensure_ascii=True)
    except:
        print("Unexpected error:", sys.exc_info()[0])
        raise
    finally:
        if session is not None:
            session.close()           

def _scopus_query_data(include_decisions = [], xtra_criteria=[]):
    col_names = ['id', 'title', 'published_year', 'doi', 'decision', 'status']

    length = int(request.args.get('iDisplayLength'))
    startIndex = int(request.args.get('iDisplayStart'))
    sortingColIndex = int(request.args.get('iSortCol_0'))
    sortDirection = request.args.get('sSortDir_0')

    searchStr = request.args.get('sSearch')
    searchFields = []
    if searchStr is not None and searchStr != "":
        # Find all the searchable fields
        for a in request.args:
            if a.startswith("bSearchable") and request.args.get(a) == "true":
                column = col_names[int(a.split("_")[1])]
                if column == "abstract": 
                    continue

                searchFields.append(column)

    searchCriteria = []
    if len(xtra_criteria) > 0:
        searchCriteria = searchCriteria + xtra_criteria

    searchFieldsMatchStr = ""
    if len(searchFields) > 0:
        searchFieldsMatchStr = searchFieldsMatchStr + " ( "
        for sIndex in range(0, len(searchFields)):
            if sIndex > 0:
                searchFieldsMatchStr = searchFieldsMatchStr + " OR "
            searchFieldsMatchStr = searchFieldsMatchStr + "(" + searchFields[sIndex] + " LIKE '%" + searchStr + "%' ) "

        searchFieldsMatchStr = searchFieldsMatchStr + ") "
        searchCriteria.append(searchFieldsMatchStr)

    if len(include_decisions) > 0:
        decisionStr = " ( decision in ( " + (",".join(["'" + x + "'" for x in include_decisions])) + ") )"
        searchCriteria.append(decisionStr)
    
    matchStr = ""
    if len(searchCriteria) > 0:
        #matchStr = " WHERE " + " AND ".join(searchCriteria) + " AND extract_id is null "
        matchStr = " WHERE " + " AND ".join(searchCriteria)

    session = None
    try:
        engine = create_engine('sqlite:///' + repository_path)  

        Session = sessionmaker(bind = engine)
        session = Session()

        total_result = engine.scalar("select count(*) from %s" % db_view_scopus)

        sql = ("select id, title, published_year, doi, decision, status, reject_reason, IFNULL(extract_id, '') extract_id from %s %s order by %s %s" % 
        (db_view_scopus, 
        matchStr,
        col_names[sortingColIndex],
        sortDirection
        ))

        df = pd.read_sql(sql, con=engine)
        recordsFiltered = len(df)
        l = []

        filter_df = df.iloc[startIndex:startIndex+length, ]
        if len(filter_df) > 0:
            filter_df = process_scopus_df(filter_df)
            l = [dict(v) for _, v in filter_df.iterrows()]

        q = {}
        q['data'] = l
        q['recordsTotal'] = total_result
        q['recordsFiltered'] = recordsFiltered

        return json.dumps(q, ensure_ascii=True)
    except:
        print("Unexpected error:", sys.exc_info()[0])
        raise
    finally:
        if session is not None:
            session.close()                       


@app.route("/auto_extract/<doi>", methods = ["GET"])
def auto_extract(doi):

    doi = doi.replace("==", "/")

    format_doi = doi.replace("/", "==")
    DOC_PATH="/Users/Zhao/Temp/pdf/" + format_doi

    INPUT_FILE = "".join([DOC_PATH, "/", format_doi, ".pdf"])
    OUTPUT_FILE = "".join([DOC_PATH, "/", format_doi, ".tei.xml"])

    if not os.path.exists(DOC_PATH):
        os.mkdir(DOC_PATH)

    if not os.path.exists(OUTPUT_FILE):
        # Download the PDF from SciHub (if any)
        sh = SciHub()
        sh.download(join("https://doi.org/", doi), path=INPUT_FILE)

        client = GrobidClient(config_path="./apps/resources/grobid.config.json")
        client.process("processFulltextDocument", DOC_PATH, consolidate_citations=False, force=True, verbose=True)
    
        print("DONE")

    # Process completed. XML available to parse
    root = etree.parse(OUTPUT_FILE)

    # abstract = root.xpath("string(//t:div/t:head[contains(text(), 'Method')]/)", namespaces={'t': 'http://www.tei-c.org/ns/1.0'})

    method = root.xpath("//t:div/t:head[contains(text(), 'Method')]", namespaces={'t': 'http://www.tei-c.org/ns/1.0'})

    method_section_number = method[0].get("n")
    if method_section_number is None:
        method = root.xpath("//t:div/t:head[contains(text(), 'Method')]/..", namespaces={'t': 'http://www.tei-c.org/ns/1.0'})
        
        content = "".join([str(tostring(m), 'utf-8') for m in method])
    else:
        method_sections = root.xpath(("//t:div/t:head[starts-with(@n, '%s')]/.." % method_section_number), namespaces={'t': 'http://www.tei-c.org/ns/1.0'})
        
        content = "".join([tostring(m) for m in method_sections])

    q = {}
    q['data'] = content
    return json.dumps(q, ensure_ascii=True)

    # onlyfiles = [f for f in listdir(OUTPUT_PATH) if isfile(join(OUTPUT_PATH, f))]
    
    # for f in onlyfiles:
    #     tree = etree.parse(join(OUTPUT_PATH, f))
        
    #     abstract = etree.XPath(".//t:abstract", namespaces={'t': 'http://www.tei-c.org/ns/1.0'})
    #     print(abstract(tree)[0])

def _str2bool(boolstr):
    if boolstr is not None and (boolstr.lower() == "on"):
        return 1
    else:
        return 0

@app.route("/submit_custom_paper_item", methods = ["POST"])
def submit_custom_paper_item():

    parent_paper_id = request.form.get('parent_paper_id')
    title = request.form.get('title')
    authors = request.form.get('authors')
    doi = request.form.get('doi')
    published_year = request.form.get('published_year')

    session = None

    try:
        engine = create_engine('sqlite:///' + repository_path)  

        # First check if the parent id exists
        existing_record = engine.scalar("select count(*) from %s where id == '%s'" % (db_view_scopus, parent_paper_id))

        if existing_record == 0:
            raise Exception("Parent with ID %s does not exists." % parent_paper_id)

        new_paper_id = "C-" + str(uuid.uuid4())
        sql = ("insert into %s (id, title, authors, doi, published_year, parent_paper_id, created_date, last_modified_date) values ('%s', %s, %s, %s, %s, %s, datetime('now'), datetime('now')) " % 
        ("sr_custom_paper", 
            new_paper_id,
            encode_sql(engine, title), 
            encode_sql(engine, authors),
            encode_sql(engine, doi), 
            encode_sql(engine, published_year), 
            encode_sql(engine, parent_paper_id)
        ))
        with engine.connect() as con:
            con.execute(sql)

    except:
        print("Unexpected error:", sys.exc_info()[0])
        raise
    finally:
        if session is not None:
            session.close()        
    
    q = {}
    q['newPaperId'] = new_paper_id
    q['status'] = "success"
    return json.dumps(q, ensure_ascii=True)

@app.route("/submit_extract_item", methods = ["POST"])
def submit_extract_item():
    # print(request.form)

    id = request.form.get('id')

    if id is not None and id != "":
        study_type = request.form.get('study_type')
        study_design = request.form.get('study_design')
        study_period = request.form.get('study_period')
        target_population = request.form.get('target_population')
        country = request.form.get('country')
        sample_size = request.form.get('sample_size')
        demographics = request.form.get('demographics')
        settings = request.form.get('settings')
        instruments_json = request.form.get('instruments_json')
        comment = request.form.get('comment')
        extract_comment = request.form.get('extract_comment')

        cri_adults = request.form.get('cri_adults')
        cri_comm_dwellers = request.form.get('cri_comm_dwellers')
        cri_article_peer_review = request.form.get('cri_article_peer_review')
        cri_article_english = request.form.get('cri_article_english')
        cri_quan_emp_study = request.form.get('cri_quan_emp_study')
        cri_repeated_instr = request.form.get('cri_repeated_instr')

        status = request.form.get('status')
        is_next_item_mode = request.form.get("next_item_mode")

        reject_reason = ""
        decision = ""

        if status == "COMPLETE":
            decision = "Pass"
        elif status == "REJECT":
            decision = "Reject-Second"
            reject_reason = request.form.get('reject_reason')
        elif status == "SAVE":
            reject_reason = request.form.get('reject_reason')

        session = None
        url = "/scopus-query-pass"

        try:
            engine = create_engine('sqlite:///' + repository_path)  
            existing_record = engine.scalar("select count(*) from %s where id == '%s'" % (db_table_extract, id))

            if existing_record > 0:
                sql = ("update %s set \
                    decision='%s', \
                    reject_reason='%s', \
                    study_type=%s, \
                    study_design=%s, \
                    study_period=%s, \
                    target_population=%s, \
                    country=%s, \
                    sample_size=%s, \
                    demographics=%s, \
                    settings=%s, \
                    comment=%s, \
                    extract_comment=%s, \
                    cri_adults=%d, \
                    cri_comm_dwellers=%d, \
                    cri_article_peer_review=%d, \
                    cri_article_english=%d, \
                    cri_quan_emp_study=%d, \
                    cri_repeated_instr=%d, \
                    status='%s', \
                    last_modified_date=datetime('now') where id='%s'" %
                (db_table_extract,
                decision,
                reject_reason,
                encode_sql(engine, study_type), 
                encode_sql(engine, study_design), 
                encode_sql(engine, study_period), 
                encode_sql(engine, target_population), 
                encode_sql(engine, country), 
                encode_sql(engine, sample_size), 
                encode_sql(engine, demographics), 
                encode_sql(engine, settings), 
                encode_sql(engine, comment),
                encode_sql(engine, extract_comment),
                _str2bool(cri_adults),
                _str2bool(cri_comm_dwellers),
                _str2bool(cri_article_peer_review),
                _str2bool(cri_article_english),
                _str2bool(cri_quan_emp_study),
                _str2bool(cri_repeated_instr),
                status,
                id)                    
                )

                #url = "/scopus-item/extract/%s" % eid
                
            else:
                sql = ("insert into %s (id, decision, reject_reason, study_type, study_design, study_period, target_population, country, sample_size, demographics, settings,  comment, extract_comment, cri_adults, cri_comm_dwellers, cri_article_peer_review, cri_article_english, cri_quan_emp_study, cri_repeated_instr, status, created_date, last_modified_date) values ('%s', '%s', '%s', %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %d, %d, %d, %d, %d, %d, '%s', datetime('now'), datetime('now')) " % 
                (db_table_extract, 
                id, decision, reject_reason, encode_sql(engine, study_type), 
                encode_sql(engine, study_design),
                encode_sql(engine, study_period), 
                encode_sql(engine, target_population), 
                encode_sql(engine, country), 
                encode_sql(engine, sample_size), 
                encode_sql(engine, demographics), 
                encode_sql(engine, settings), 
                encode_sql(engine, comment),
                encode_sql(engine, extract_comment),
                _str2bool(cri_adults),
                _str2bool(cri_comm_dwellers),
                _str2bool(cri_article_peer_review),
                _str2bool(cri_article_english),
                _str2bool(cri_quan_emp_study),
                _str2bool(cri_repeated_instr),
                status
                ))

            delete_ins_sql = "delete from %s where id = '%s'" % (db_table_instr_extract, id)
            ins_insert_sqls = []

            instruments = json.loads(instruments_json)

            for i in instruments:
                new_ins_sql = ("insert into %s (id, instrument_name, instrument_ref_year, admin_mode, admin_frequency, structure, number_of_items, version, response_format, measured_duration, modifications, terms_of_use, construct_measured, rationale, theoretical_framework, created_date, last_modified_date) values ('%s', %s, %s, '%s', %s, %s, %s, %s, %s, %s, %s, '%s', %s, %s, %s, datetime('now'), datetime('now')) " % 
                (db_table_instr_extract,
                id, 
                encode_sql(engine, i['instrument_name']), 
                encode_sql(engine, i['instrument_ref_year']), 
                i['admin_mode'], 
                encode_sql(engine, i['admin_frequency']), 
                encode_sql(engine, i['structure']), 
                encode_sql(engine, i['number_of_items']), 
                encode_sql(engine, i['version']), 
                encode_sql(engine, i['response_format']), 
                encode_sql(engine, i['measured_duration']),                 
                encode_sql(engine, i['modifications']), 
                i['terms_of_use'], 
                encode_sql(engine, i['construct_measured']),
                encode_sql(engine, i['rationale']), 
                encode_sql(engine, i['theoretical_framework'])))

                ins_insert_sqls.append(new_ins_sql)

            with engine.connect() as con:
                con.execute(sql)

                print(delete_ins_sql)
                con.execute(delete_ins_sql)

                for s in ins_insert_sqls:
                    print(s)
                    con.execute(s)

        except:
            print("Unexpected error:", sys.exc_info()[0])
            raise
        finally:
            if session is not None:
                session.close()        
    
    #return redirect("/scopus-query-pass", code=302)
    # if request.form.get('extract-mode') is not None:
    #     return redirect("/scopus-next-extract", code=302)
    # else:
    #     return "<html><head></head><body onload='window.close();'>Record is updated successfully.</body></html>"
    if status == "COMPLETE" or status == "REJECT" or status == "IGNORE_REVIEW":
        if is_next_item_mode == "true":
            url = "/next-item"
        else: 
            url = "/"
    else:
        if is_next_item_mode == "true":
            url = "/scopus-item/extract/%s?next_item_mode=true" % id
        else:
            url = "/scopus-item/extract/%s" % id

    return redirect(url, code = 302)


def encode_sql(engine, s):
    if s is not None:
        return String('').literal_processor(dialect=engine.dialect)(s)
    else:
        return "NULL"

@app.route("/submit_scopus_item", methods = ["POST"])
def submit_scopus_item():
    #print(request.form)

    id = request.form.get('id')
    decision = request.form.get('decision')
    reject_reason = request.form.getlist('reject_reason')
    comment = request.form.get('comment')

    if id is not None and id != "":
        session = None
        url = "/scopus-first-pass"

        try:
            engine = create_engine('sqlite:///' + repository_path)  
            existing_record = engine.scalar("select count(*) from %s where id == '%s'" % (db_table_screen, id))

            if existing_record > 0:
                sql = ("update %s set decision='%s', reject_reason='%s', comment=%s, last_modified_date=datetime('now') where id='%s'" %
                (db_table_screen, decision, ",".join(reject_reason), encode_sql(engine, comment), id))

                url = "/scopus-item/%s" % id
            else:
                sql = ("insert into %s (id, decision, reject_reason, comment, created_date, last_modified_date) values ('%s', '%s', '%s', %s, datetime('now'), datetime('now')) " % (db_table_screen, id, decision, ",".join(reject_reason), encode_sql(engine, comment)))

            with engine.connect() as con:
                rs = con.execute(sql)
        except:
            print("Unexpected error:", sys.exc_info()[0])
            raise
        finally:
            if session is not None:
                session.close()        
    
    return redirect(url, code=302)

@app.route("/scopus-first-pass", methods = ["GET"])
def scopus_first_pass():
    session = None
    try:
        engine = create_engine('sqlite:///' + repository_path)  

        Session = sessionmaker(bind = engine)
        session = Session()

        sql = ("select id, title, doi, decision, published_year from " + db_view_scopus + " where decision is null and id not like 'C-%' order by published_year desc limit 1") 

        print(sql)

        df = pd.read_sql(sql, con=engine)
        df = process_one_scopus(df)

        q = {}

        if len(df) > 0:
            q = df.iloc[0]

        return render_template('scopus_first_pass_entry.html', article = q)  
    except:
        print("Unexpected error:", sys.exc_info()[0])
        raise
    finally:
        if session is not None:
            session.close()    

@app.route("/scopus-reject-no-reason", methods = ["GET"])
def scopus_reject_no_reason():
    session = None
    try:
        engine = create_engine('sqlite:///' + repository_path)  

        Session = sessionmaker(bind = engine)
        session = Session()

        total_reject_reason = engine.scalar("select count(*) from %s where decision == 'Reject' and reject_reason is null" % db_view_scopus)
        sql = ("select id, title, doi, decision, published_year from %s where \
        decision == 'Reject' and reject_reason is null limit 1" % db_view_scopus)

        print(sql)

        df = pd.read_sql(sql, con=engine)
        df = process_one_scopus(df)

        q = {}

        if len(df) > 0:
            q = df.iloc[0]

        return render_template('scopus_first_pass_entry.html', article = q, total_reject_reason = total_reject_reason)  
    except:
        print("Unexpected error:", sys.exc_info()[0])
        raise
    finally:
        if session is not None:
            session.close()                

@app.route("/scopus-item/<id>", methods = ["GET"])
def scopus_open_item(id):
    session = None
    try:
        engine = create_engine('sqlite:///' + repository_path)  

        Session = sessionmaker(bind = engine)
        session = Session()

        sql = (("select id, title, doi, decision, reject_reason, comment, published_year from %s where id = '"  % db_view_scopus) + id + "'")

        print(sql)

        df = pd.read_sql(sql, con=engine)
        df = process_one_scopus(df)

        q = {}

        if len(df) > 0:
            q = df.iloc[0]

        return render_template('scopus_first_pass_entry.html', article = q)  
    except:
        print("Unexpected error:", sys.exc_info()[0])
        raise
    finally:
        if session is not None:
            session.close()   


@app.route("/next-item", methods = ["GET"])
def next_item():
    session = None

    try:
        engine = create_engine('sqlite:///' + repository_path)  

        Session = sessionmaker(bind = engine)
        session = Session()

        sql = ("select * from %s where decision is null and extract_id is null order by published_year desc limit 1" % db_view_scopus)

        df = pd.read_sql(sql, con=engine)
        df = process_one_scopus(df)
        q = {}

        if len(df) > 0:
            q = df.iloc[0]

        id = q['id']
        url = "/scopus-item/extract/%s?next_item_mode=true" % q['id']
        return redirect(url, code = 302)
    except:
        print("Unexpected error:", sys.exc_info()[0])
        raise
    finally:
        if session is not None:
            session.close()

@app.route("/scopus-next-extract", methods = ["GET"])
def scopus_next_extract():
    session = None

    try:
        engine = create_engine('sqlite:///' + repository_path)  

        Session = sessionmaker(bind = engine)
        session = Session()

        total_extract_outstanding = engine.scalar("select count(*) from %s where decision == 'Pass' and extract_id is null" % db_view_scopus)
        sql = ("select * from %s where decision == 'Pass' and extract_id is null order by published_year desc limit 1" % db_view_scopus)

        df = pd.read_sql(sql, con=engine)
        df = process_one_scopus(df)
        q = {}

        if len(df) > 0:
            q = df.iloc[0]

        sql = ("select * from %s where id = '" % db_table_instr_extract) + q['id'] + "'"
        instruments_df = pd.read_sql(sql, con=engine)
        instruments_json = json.dumps([dict(v) for _, v in instruments_df.iterrows()])

        print(instruments_json)
        
        return render_template('scopus_extract_entry.html', article = q, ins = instruments_json, total_extract_outstanding = total_extract_outstanding, extract_mode = True) 
    except:
        print("Unexpected error:", sys.exc_info()[0])
        raise
    finally:
        if session is not None:
            session.close()                  

@app.route("/scopus-item/extract/<id>", methods = ["GET"])
def scopus_open_item_extract(id):
    session = None
    try:
        engine = create_engine('sqlite:///' + repository_path)  

        Session = sessionmaker(bind = engine)
        session = Session()

        total = engine.scalar("select count(*) from %s" % db_view_scopus)
        total_pass = engine.scalar("select count(*) from %s where decision == 'Pass'" % db_view_scopus)
        total_reject = engine.scalar("select count(*) from %s where decision == 'Reject-Second'" % db_view_scopus)
        total_save = engine.scalar("select count(*) from %s where status == 'SAVE'" % db_view_scopus)
        total_extract_outstanding = total - total_pass - total_reject - total_save
        
        sql = ("select * from %s where id = '" + id + "'") % db_view_scopus

        df = pd.read_sql(sql, con=engine)
        df = process_one_scopus(df)
        q = {}

        if len(df) > 0:
            q = df.iloc[0]

        sql = ("select * from %s where id = '" % db_table_instr_extract) + id + "'"
        instruments_df = pd.read_sql(sql, con=engine)
        instruments_json = json.dumps([dict(v) for _, v in instruments_df.iterrows()])

        # print(instruments_json)
        
        return render_template('scopus_extract_entry.html', article = q, ins = instruments_json, total_extract_outstanding = total_extract_outstanding)  
    except:
        print("Unexpected error:", sys.exc_info()[0])
        raise
    finally:
        if session is not None:
            session.close()                  

@app.route("/")
def homepage():
    try:
        return render_template('home.html')
    except:
        print("Unexpected error:", sys.exc_info()[0])
        raise

#ui = WebUI(app, debug=True) # Create a WebUI instance

if __name__ == '__main__':
    app.run(debug=True, host = "127.0.0.1", port=5555)
    #ui.run()

