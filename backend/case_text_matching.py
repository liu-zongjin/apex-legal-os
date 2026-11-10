"""Conservative literal matching of case references in natural language."""
import re

# Common legal and administrative wording is not a case identifier.
GENERIC = ('建设工程施工合同纠纷', '案件', '公司', '有限', '责任', '集团', '建设工程', '施工合同', '合同纠纷',
           '人民法院', '开庭', '提交', '之前', '提醒', '通知', '律师', '当事人', '材料')


def normalize(value):
    return re.sub(r'[^\w\u4e00-\u9fff]', '', str(value or '').lower())


def match_case_text(text, rows):
    source = normalize(text)
    matches = {}
    for row in rows:
        identifiers = [normalize(row.get('title')), normalize(row.get('party_name'))]
        evidence = set()
        for identifier in identifiers:
            # Four consecutive characters are much less likely to be an incidental
            # overlap than a two-character word. The original source must contain it.
            for index in range(max(0, len(identifier) - 3)):
                token = identifier[index:index + 4]
                if token in source and not any(token in term or term in token for term in GENERIC):
                    if re.search(r'[\u4e00-\u9fff]{4}', token):
                        evidence.add(token)
        if evidence:
            matches[row['case_id']] = row
    return next(iter(matches.values())) if len(matches) == 1 else None
