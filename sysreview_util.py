import configparser
import json
import math
import re
import os

class sysreview:

    SCREENING_REJECT_REASONS = [ \
    {"key": "POP_ADOLESCENT", "label": "Population - Adolescent"}, \
    {"key": "POP_CHILDREN", "label": "Population - Children"}, \
    {"key": "POP_COUNTRIES", "label": "Population - Other Countries"}, \
    {"key": "POP_NON_COMMUNITY", "label": "Population - Non community dwellers"}, \
    {"key": "POP_SCHOOL", "label": "Population - School (up to High School)"}, \
    {"key": "INSTR_NON_ENGLISH", "label": "Instrument - Non-English"}, \
    {"key": "INSTR_NON_DIGITAL", "label": "Instrument - Non-Digital"}, \
    {"key": "INSTR_NOT_REPEAT", "label": "Instrument - Not Repeated"}, \
    {"key": "INSTR_NOT_SELF_REPORT", "label": "Instrument - Not Self-Report"}, \
    {"key": "OTHER_DUPLICATE", "label": "Other - Duplicate"}, \
    {"key": "OTHER_404", "label": "Other - Paper Not Found"}, \
    {"key": "OTHER_REASONS", "label": "Other - Specific Reasons"}, \
    {"key": "STUDY_PILOT", "label": "Study - Feasibility/Pilot/Exploratory"}, \
    {"key": "STUDY_IRRELEVANT", "label": "Study - Irrelevant"}, \
    {"key": "STUDY_CASE_REPORT", "label": "Study - Case Report"}, \
    {"key": "STUDY_NON_ENGLISH", "label": "Study - Non-English"}, \
    {"key": "STUDY_OTHER_ARTICLES", "label": "Study - Opinions, Conceptual, Theoretical Articles, Brief Report, Guidelines, Retraction, Letters, Commentary"}, \
    {"key": "STUDY_PROTOCOL", "label": "Study - Protocol"}, \
    {"key": "STUDY_QUALITATIVE", "label": "Study - Qualitative"}, \
    {"key": "STUDY_SECOND_ANALYSIS", "label": "Study - Secondary Analysis"}, \
    {"key": "_UNKNW_INSTR_LANG", "label": "Follow-up - Unknown Instrument Language"}, \
    {"key": "_UNKNW_IN_OUT", "label": "Follow-up - Grey List"}, \
    {"key": "OTHER_NO_DOI", "label": "Other - No DOI"}]


    ABSTRACT_EXTRACT_XPATH = [ \
        "//section[contains(@class, 'article-section__abstract')]",
        "//div[@id='Abs1-section']",
        "//div[@id='Abs1-content']",
        "//div[@id='dpabstract']",
        "//div[contains(@class, 'abstractSection') and contains(@class, 'abstractInFull')]",
        "//div[@class='abstract author' and @lang='en']",
        "//div[contains(@class, 'realAbstract')]",
        "//div[contains(@class, 'article-section__content')]",
        "//div[contains(@class, 'JournalAbstract')]",
        "//div[contains(@class, 'NLM_paragraph')]",
        "//div[contains(@class, 'magArticleAbstract')]",
        "//p[contains(@class, 'abst')]",
        "//div[contains(@class, 'art-abstract')]",
        "//h2/span[contains(text(), 'Abstract')]/../../div[contains(@class, 'section-paragraph')]",
        "//div[@class='abstract author']",
        "//div[@class='section-right']/div[@class='content']",
        "//strong[contains(text(), 'Abstract')]/../following-sibling::div[1]",
        "//div[contains(@class, 'abstract author')]",
        "//article[contains(@class, 'abstract')]",
        "//section[contains(@class, 'abstract')]",
        "//section[contains(@id, 'abstract')]",
        "//div[contains(@class, 'abstract')]",
        "//div[contains(@id, 'abstract')]",
        "//div[contains(@class, 'article__sections')]/section[1]",
        "//div[@id='article1-front']",
        "//div[@class='content']"
    ]    


    def cleanse_text(text):
        text = text.replace("â€™", "'")
        text = text.replace("â€œ", "\"")
        text = text.replace("â€", "\"")
        text = text.replace("â€”", "-")

        return text

    def calculate_interest_score(positive_words, negative_words, content):
        pw_matches = []
        nw_matches = []

        for w in positive_words:
            num_matches = len(re.findall(w['word'], content))
            if num_matches > 0:
               pw_matches.append({"word": w['word'], "no_of_words": len(w['word'].split()), "weight": w["weight"], "count": num_matches})

        for w in negative_words:
            num_matches = len(re.findall(w['word'], content))
            if num_matches > 0:
               nw_matches.append({"word": w['word'], "no_of_words": len(w['word'].split()), "weight": w["weight"], "count": num_matches})

        positive_score = 0
        negative_score = 0

        num_of_words = len(content.split())
        positive_score = sum([x['weight']/10 * (x['count']*x['no_of_words'])/num_of_words for x in pw_matches])
        negative_score = sum([x['weight']/10 * (x['count']*x['no_of_words'])/num_of_words for x in nw_matches])
        
        # print("%.2f %s" % (positive_score, str(pw_matches)))
        # print("%.2f %s" % (negative_score, str(nw_matches)))

        return positive_score - (negative_score * 1.2)
