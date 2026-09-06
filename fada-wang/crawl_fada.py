#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
法答网精选答问爬虫脚本
抓取最高人民法院网站上的所有法答网精选答问内容
支持增量更新：只爬取新增的批次
"""

import requests
from bs4 import BeautifulSoup
import json
import os
import re
from datetime import datetime
from typing import List, Dict, Tuple

# ─── 数据目录（固定为脚本所在目录下的 data/ 子目录）─────────────────
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_DATA_DIR = os.path.join(_SCRIPT_DIR, 'data')

# 请求头
headers = {
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
}

# 所有法答网精选答问的链接（按发布时间倒序）
links = [
    ('法答网精选答问（第三十七批）——执行工作专题', 'https://www.court.gov.cn/zixun/xiangqing/488441.html'),
    ('法答网精选答问（第三十六批）——国家赔偿专题', 'https://www.court.gov.cn/zixun/xiangqing/487091.html'),
    ('法答网精选答问（第三十五批）——商事审判专题', 'https://www.court.gov.cn/zixun/xiangqing/485941.html'),
    ('法答网精选答问（第三十四批）——仲裁司法审查专题（第二批）', 'https://www.court.gov.cn/zixun/xiangqing/484391.html'),
    ('法答网精选答问（第三十三批）——知识产权司法保护专题', 'https://www.court.gov.cn/zixun/xiangqing/483111.html'),
    ('法答网精选答问（第三十二批）——环境资源专题', 'https://www.court.gov.cn/zixun/xiangqing/481991.html'),
    ('法答网精选答问（第三十一批）——植物新品种专题', 'https://www.court.gov.cn/zixun/xiangqing/481361.html'),
    ('法答网精选答问（第三十批）——反垄断专题', 'https://www.court.gov.cn/zixun/xiangqing/481371.html'),
    ('法答网精选答问（第二十九批）——保障规范律师诉讼行为专题', 'https://www.court.gov.cn/zixun/xiangqing/480761.html'),
    ('法答网精选答问（第二十八批）——食品药品惩罚性赔偿专题', 'https://www.court.gov.cn/zixun/xiangqing/478831.html'),
    ('法答网精选答问（第二十七批）——未成年人司法保护专题', None),  # 最高人民法院官网未发布，使用补充数据
    ('法答网精选答问（第二十六批）——民营企业保护专题', 'https://www.court.gov.cn/zixun/xiangqing/472471.html'),
    ('法答网精选答问（第二十五批）——引渡案件审查专题', 'https://www.court.gov.cn/zixun/xiangqing/471151.html'),
    ('法答网精选答问（第二十四批）——串通投标罪专题', 'https://www.court.gov.cn/zixun/xiangqing/469691.html'),
    ('法答网精选答问（第二十三批）——婚姻家庭专题', 'https://www.court.gov.cn/zixun/xiangqing/469701.html'),
    ('法答网精选答问（第二十二批）', 'https://www.court.gov.cn/zixun/xiangqing/469021.html'),
    ('法答网精选答问（第二十一批）——人民陪审专题', 'https://www.court.gov.cn/zixun/xiangqing/466371.html'),
    ('法答网精选答问（第二十批）——诉讼时效专题', 'https://www.court.gov.cn/zixun/xiangqing/465691.html'),
    ('法答网精选答问（第十九批）——人格权专题', 'https://www.court.gov.cn/zixun/xiangqing/464401.html'),
    ('法答网精选答问（第十八批）——工伤保险待遇专题', None),  # 最高人民法院官网未发布，使用补充数据
    ('法答网精选答问（第十七批）——民法典合同编通则专题', 'https://www.court.gov.cn/zixun/xiangqing/459181.html'),
    ('法答网精选答问（第十六批）——国家赔偿及司法救助专题', 'https://www.court.gov.cn/zixun/xiangqing/455371.html'),
    ('法答网精选答问（第十五批）——立案受理专题', 'https://www.court.gov.cn/zixun/xiangqing/452221.html'),
    ('法答网精选答问（第十四批）——仲裁司法审查专题', 'https://www.court.gov.cn/zixun/xiangqing/451061.html'),
    ('法答网精选答问（第十三批）——行政诉讼专题', 'https://www.court.gov.cn/zixun/xiangqing/451051.html'),
    ('法答网精选答问（第十二批）——组织、领导传销活动罪专题', 'https://www.court.gov.cn/zixun/xiangqing/448831.html'),
    ('法答网精选答问（第十一批）', 'https://www.court.gov.cn/zixun/xiangqing/448271.html'),
    ('法答网精选答问（第十批）', 'https://www.court.gov.cn/zixun/xiangqing/446311.html'),
    ('法答网精选答问（第九批）', 'https://www.court.gov.cn/zixun/xiangqing/441371.html'),
    ('法答网精选答问（第八批）', 'https://www.court.gov.cn/zixun/xiangqing/439701.html'),
    ('法答网精选答问（第七批）', 'https://www.court.gov.cn/zixun/xiangqing/438391.html'),
    ('法答网精选答问（第六批）', 'https://www.court.gov.cn/zixun/xiangqing/434921.html'),
    ('法答网精选答问（第五批）', 'https://www.court.gov.cn/zixun/xiangqing/433701.html'),
    ('法答网精选答问（第四批）', 'https://www.court.gov.cn/zixun/xiangqing/429992.html'),
    ('法答网精选答问（第三批）', 'https://www.court.gov.cn/zixun/xiangqing/428772.html'),
    ('法答网精选答问（第二批）', 'https://www.court.gov.cn/zixun/xiangqing/426912.html'),
    ('法答网精选答问（第一批）', 'https://www.court.gov.cn/zixun/xiangqing/426272.html'),
]

# 缺失批次的补充数据
MISSING_BATCHES_DATA = {
    '法答网精选答问（第十八批）——工伤保险待遇专题': {
        'url': 'https://www.sohu.com/a/893024654_121123767',
        'publish_date': '2025-05-08',
        'qa_pairs': [
            {
                'question': '问题1：工伤保险中有关工作原因、工作时间和工作场所的认定如何把握？',
                'answer': '答疑意见：依照社会保险法第三十六条以及《工伤保险条例》第一条、第十四条的规定，工伤认定应当重点围绕工作原因进行。工作场所、工作时间是工伤认定的辅助要素，在工作原因无法查明时，工作场所、工作时间的因素可以用来认定是否属于工作原因。比如，对于用人单位安排职工居家办公，有证据证明职工在工作时间确因工作原因受到事故伤害的，不应因在家工作而影响工伤认定。根据指导案例40号（孙立兴诉天津新技术产业园区劳动人事局工伤认定案）的裁判要旨，"因工作原因"是指职工受伤与其从事本职工作之间存在关联关系。实践中，对工作原因的认定，应当综合考虑是否属于工作或者作为工作安排的活动、是否属于履行工作职责、是否受用人单位指派、是否与工作职责有关、是否基于用人单位的正当利益、是否属于工作期间在合理场所解决必需的基本需求等因素。对工作时间的认定，应当考虑是否属于法律规定的或者用人单位要求职工工作的时间，包括劳动合同约定、用人单位规定或者法律规定的工作时间，以及完成用人单位临时指派或者特定工作任务的时间、加班时间等。对工作场所的认定，应当考虑是否属于与职工工作职责相关的区域以及因履行工作职责所需的合理区域，包括但不限于：（一）用人单位能够对从事日常生产经营活动进行有效管理的区域；（二）职工为完成某项特定工作所涉及的单位以外的相关区域；（三）职工因工作来往于多个工作地点之间的合理区域。\n\n咨询人：四川省理塘县人民法院立案庭（诉讼服务中心） 洛绒布克\n\n答疑专家：最高人民法院行政庭 王晓滨'
            },
            {
                'question': '问题2：建筑企业已办理项目参保但未在农民工上岗前办理人员增减参保手续的，工伤保险待遇是否由社会保险基金支付？',
                'answer': '答疑意见：按照建设项目参加工伤保险，是指按照工程项目施工承包合同总造价缴纳工伤保险费，并非按照通常的工资总额缴纳。这既是对建筑企业的强制性要求，也是对建筑企业的职工特别是流动性较大的农民工给予的特殊保护。缴纳项目工伤保险，应覆盖项目中的所有职工。建筑企业应当对全部施工人员实行动态实名制管理，将人员增减变更情况及时报送社保经办机构。原则上，社会保险基金支付工伤保险待遇应以向社保经办机构报备的人员为准。因未及时更新人员增减参保手续，未经报备的劳动者发生工伤后是否由社会保险基金支付工伤保险待遇，应当考虑劳动者是否符合项目参保时间、范围，是否实际参与了参保项目的施工，是否可以确定劳动关系或者事实劳动关系等因素，结合具体案情综合判断。原则上，如劳动者在参保期内、项目范围内实际参与了施工，能够确定劳动关系或事实劳动关系的，社会保险机构不应仅以未报备为由拒付待遇。\n\n咨询人：四川省内江市中级人民法院行政庭 王晶\n\n答疑专家：四川省高级人民法院行政庭（赔偿办） 刘丽君'
            },
            {
                'question': '问题3：建筑领域无用工主体资格的承包人所聘用人员因工伤亡，诉请工伤保险待遇赔偿，是否需经工伤认定等前置程序？',
                'answer': '答疑意见：建筑领域中，多层转包导致存在多个承包主体。在此情况下，如果承包人没有用工主体资格，那么承包人所聘用的劳动者因工死亡后，其近亲属向法院起诉要求支付工伤保险待遇，必须经过工伤认定的前置程序。人民法院在民事案件审理中，不能直接认定工伤。《工伤保险条例》第十八条规定，提出工伤认定申请应当提交工伤认定申请表、与用人单位存在劳动关系的证明、医疗诊断证明等材料。也就是说，工伤认定属于劳动行政部门的职责范围。法院在审理此类案件时，如果当事人没有经过工伤认定程序，应当告知当事人先向劳动行政部门申请工伤认定。待工伤认定后，如果当事人对认定结果不服，可以依法申请行政复议或者提起行政诉讼。如果当事人不服劳动仲裁裁决提起民事诉讼，人民法院应当依法审理。\n\n咨询人：内蒙古自治区高级人民法院赔偿委员会办公室 张雷\n\n答疑专家：最高人民法院民一庭 谢爱梅'
            },
            {
                'question': '问题4：冒用他人名义入职者在被认定为工伤后，能否享受工伤保险待遇？',
                'answer': '答疑意见：在用人单位以被冒用人身份为劳动者缴纳工伤保险的情形下，如果劳动者冒用他人名义入职的目的是为了获得工作机会，而非骗取工伤保险待遇，那么在劳动者被认定为工伤后，其应当享受工伤保险待遇。理由如下：第一，从工伤保险制度的目的看，工伤保险是为保障因工作遭受事故伤害或者患职业病的职工获得医疗救治和经济补偿。如果劳动者确实因工作原因受到事故伤害，且用人单位已经为其缴纳了工伤保险，就应当享受工伤保险待遇，这符合工伤保险制度的设立目的。第二，从用人单位的过错看，用人单位在招录员工时负有审查义务，如果用人单位没有尽到审查义务，导致劳动者能够冒用他人名义入职，用人单位存在过错。在这种情况下，不允许劳动者享受工伤保险待遇，对劳动者不公平。第三，从法律后果看，劳动者冒用他人名义入职的行为，违反了劳动法的相关规定，应当承担相应的法律责任。但是，这种违法行为与工伤认定和工伤保险待遇的享受，是两个不同的法律问题。不能因为劳动者存在违法行为，就剥夺其享受工伤保险待遇的权利。同时，需要指出的是，劳动者冒用他人名义入职的行为，可能给被冒用人造成损害，被冒用人可以依法向劳动者主张赔偿。用人单位也可以因劳动者的违法行为，依法解除与劳动者的劳动关系。\n\n咨询人：江西省高级人民法院行政审判庭 蔡维琴\n\n答疑专家：最高人民法院行政庭 韩锦霞'
            },
            {
                'question': '问题5：工伤职工在停工留薪期内死亡，其近亲属享受工亡待遇是否需要提交因果关系的鉴定？举证责任由谁承担？',
                'answer': '答疑意见：工伤职工在停工留薪期内死亡，其近亲属能否享受工亡待遇，需要证明职工的死亡与工伤之间存在因果关系。根据《工伤保险条例》第三十九条的规定，职工因工死亡的，其近亲属可以从工伤保险基金领取丧葬补助金、供养亲属抚恤金和一次性工亡补助金。但是，职工在停工留薪期内死亡，如果无法证明死亡与工伤之间存在因果关系，就不能享受工亡待遇。在实践中，如何证明因果关系，是争议的焦点。关于因果关系证明，首先，申请工亡认定时，职工的近亲属应当向社会保险行政部门提交死亡与工伤存在因果关系的证明材料。如果无法提交，社会保险行政部门可以不予认定工亡。其次，如果社会保险行政部门不予认定工亡，职工的近亲属可以依法申请行政复议或者提起行政诉讼。在行政诉讼中，社会保险行政部门对不予认定工亡的决定承担举证责任，证明其作出的决定合法。但是，这并不免除职工近亲属的举证责任。职工的近亲属应当提供证据证明死亡与工伤之间存在因果关系。如果职工的近亲属无法提供证据，或者提供的证据不足以证明因果关系，社会保险行政部门的不予认定工亡的决定，应当予以支持。再次，在民事诉讼中，如果职工的近亲属起诉要求享受工亡待遇，职工的近亲属应当提供证据证明死亡与工伤之间存在因果关系。如果无法提供证据，应当承担举证不能的不利后果。\n\n咨询人：贵州省高级人民法院行政审判庭 陈炜燚\n\n答疑专家：最高人民法院行政庭 王晓滨'
            }
        ]
    },
    '法答网精选答问（第二十七批）——未成年人司法保护专题': {
        'url': 'https://weibo.com/u/3951684911',
        'publish_date': '2025-10-11',
        'qa_pairs': [
            {
                'question': '问题1：男女双方未离婚，一方以子女名义主张分居期间的抚养费，应否支持？',
                'answer': '答疑意见：《最高人民法院关于适用〈中华人民共和国民法典〉婚姻家庭编的解释（一）》第四十三条规定："婚姻关系存续期间，父母双方或者一方拒不履行抚养子女义务，未成年子女或者不能独立生活的成年子女请求支付抚养费的，人民法院应予支持。"这一规定明确了在婚姻关系存续期间，父母一方可以以子女的名义起诉要求另一方支付抚养费。这里的关键是"拒不履行抚养子女义务"，即有履行条件和履行能力而不履行，主观上存在可追责性，需要结合具体案情判断。如果双方只是因感情不和而分居，但双方都有抚养能力且都实际履行了抚养义务，只是分居期间一方没有直接照顾子女，这种情况下一般不支持抚养费请求。如果一方明确表示不支付抚养费，或者有抚养能力但实际不支付，导致子女生活困难，这种情况下应当支持抚养费请求。\n\n咨询人：北京市第一中级人民法院少年家事庭 张琦\n\n答疑专家：最高人民法院民一庭 王丹'
            },
            {
                'question': '问题2：抚养费纠纷案件诉讼费的收费标准如何认定？',
                'answer': '答疑意见：根据《诉讼费用交纳办法》的规定，财产案件根据诉讼请求的金额或者价额，按比例分段累计交纳。抚养费纠纷案件属于财产案件，应当按照财产案件的收费标准交纳诉讼费。但是，需要注意以下几点：第一，抚养费纠纷案件的诉讼费计算基数不是固定的，而是根据当事人请求的抚养费金额计算。如果当事人请求的抚养费是按月支付的，应当计算一定期限内的总金额。第二，对于抚养费纠纷案件，如果当事人确有困难，可以申请缓交、减交或者免交诉讼费。人民法院应当根据当事人的经济状况和案件情况，决定是否准许。第三，对于抚养费纠纷案件，如果当事人一方是未成年人或者不能独立生活的成年子女，且经济困难，人民法院可以根据案件情况，适当降低诉讼费收费标准或者减免诉讼费。\n\n咨询人：上海市第一中级人民法院少年家事庭 李兴\n\n答疑专家：最高人民法院立案庭 闫宏波'
            },
            {
                'question': '问题3：申请执行人申请给付抚养费，是否受到申请执行时效的限制？',
                'answer': '答疑意见：抚养费执行申请是否受时效限制，需要区分不同情况。根据《民法典》第一百九十六条的规定，请求支付抚养费、赡养费或者扶养费的请求权，不适用诉讼时效。但是，这不意味着抚养费执行申请完全不受时效限制。对于已经生效的抚养费判决，如果被执行人不履行，申请执行人申请强制执行的，应当遵守申请执行时效的规定。《民事诉讼法》第二百四十六条规定，申请执行的期间为二年。申请执行时效的中止、中断，适用法律有关诉讼时效中止、中断的规定。因此，对于抚养费判决，申请执行人应当在判决生效后二年内申请强制执行。如果超过二年未申请执行，被执行人提出异议的，人民法院不予支持。但是，需要指出的是，对于尚未到期的抚养费，申请执行人可以定期申请执行，不受申请执行时效的限制。\n\n咨询人：浙江省杭州市中级人民法院执行局 陈剑\n\n答疑专家：最高人民法院执行局 熊劲松'
            },
            {
                'question': '问题4：人民法院应当如何开展家庭教育指导，以实现案件办理政治效果、社会效果、法律效果统一？',
                'answer': '答疑意见：《中华人民共和国家庭教育促进法》实施后，人民法院在审理涉未成年人案件时，应当积极开展家庭教育指导。第一，明确家庭教育指导的适用范围。在审理离婚案件、抚养权纠纷、监护权纠纷等涉未成年人案件时，如果发现父母或者其他监护人不正确实施家庭教育，侵害未成年人合法权益的，应当依法予以训诫，并可以责令其接受家庭教育指导。第二，明确家庭教育指导的内容。家庭教育指导应当包括：家庭教育理念、家庭教育方法、未成年人保护法律知识、未成年人心理健康知识等。人民法院可以根据案件具体情况，邀请专业人士参与家庭教育指导。第三，明确家庭教育指导的方式。人民法院可以采用当面指导、书面指导、远程指导等方式开展家庭教育指导。对于拒不接受家庭教育指导的父母或者其他监护人，人民法院可以依法采取训诫、罚款、拘留等措施。第四，明确家庭教育指导的衔接。人民法院应当与教育部门、民政部门、妇联等部门建立协作机制，共同推进家庭教育指导工作。\n\n咨询人：江苏省南京市中级人民法院少年家事庭 周侃\n\n答疑专家：最高人民法院民一庭 王丹'
            },
            {
                'question': '问题5：刑事案件中未成年人心理测评报告的证据属性如何认定？',
                'answer': '答疑意见：未成年人心理测评报告是人民法院在审理涉未成年人刑事案件时经常遇到的一类证据。对于未成年人心理测评报告的证据属性，应当根据其制作主体、制作程序、内容性质等因素综合判断。第一，如果未成年人心理测评报告是由具备资质的心理测评机构或者专业人员制作，且制作程序符合法律规定，该报告应当认定为鉴定意见，属于法定证据种类。第二，如果未成年人心理测评报告是由不具备资质的人员制作，或者制作程序不符合法律规定，该报告不能作为鉴定意见，但可以作为其他类型的证据使用，如证人证言、书证等。第三，对于未成年人心理测评报告的审查，人民法院应当重点审查以下方面：制作主体是否具备资质、制作程序是否合法、测评方法是否科学、测评结论是否客观等。第四，如果未成年人心理测评报告与其他证据存在矛盾，人民法院应当综合全案证据，判断其证明力。\n\n咨询人：广东省广州市中级人民法院少年家事庭 赵俊\n\n答疑专家：最高人民法院刑一庭 于同志'
            }
        ]
    }
}

def fetch_page(url):
    """获取页面内容"""
    try:
        response = requests.get(url, headers=headers, timeout=30)
        response.encoding = 'utf-8'
        return response.text
    except Exception as e:
        print(f"获取页面失败: {url}, 错误: {e}")
        return None

def parse_content(html):
    """解析页面内容，提取问答和发布时间"""
    soup = BeautifulSoup(html, 'html.parser')

    # 查找主要内容区域
    content_div = soup.find('div', class_='txt_txt')
    if not content_div:
        content_div = soup.find('div', id='content')
    if not content_div:
        content_div = soup.find('div', class_='text')
    if not content_div:
        content_div = soup.find('div', class_='content')

    if not content_div:
        return [], None

    # 提取发布时间
    publish_date = None
    # 尝试多种方式查找发布时间
    date_patterns = [
        lambda s: s.find('span', string=lambda x: x and '发布时间' in x),
        lambda s: s.find(string=lambda x: x and '发布时间' in x),
    ]

    for pattern in date_patterns:
        result = pattern(soup)
        if result:
            # 提取日期部分
            if hasattr(result, 'get_text'):
                date_text = result.get_text()
            else:
                date_text = result
            # 尝试提取日期格式
            import re
            date_match = re.search(r'(\d{4}-\d{2}-\d{2})', date_text)
            if date_match:
                publish_date = date_match.group(1)
                break

    # 提取问答内容
    qa_pairs = []

    # 检查页面结构
    p_tags = content_div.find_all('p')
    strong_tags = content_div.find_all('strong')

    # 判断页面结构类型
    # 如果有<p>标签且<p>中包含"问题"文本，使用<p>解析
    has_p_with_question = False
    for p in p_tags:
        if p.get_text(strip=True).startswith('问题'):
            has_p_with_question = True
            break

    if has_p_with_question:
        # 方法1：使用<p>标签解析（适用于问题在单独<p>中的页面）
        i = 0
        while i < len(p_tags):
            p_tag = p_tags[i]
            p_content = p_tag.get_text(strip=True)

            # 检查这个<p>标签是否包含问题（以"问题"开头）
            if p_content.startswith('问题'):
                question_text = p_content

                # 开始收集答案内容
                answer_parts = []

                # 继续遍历后续的<p>标签，直到遇到下一个问题
                j = i + 1
                while j < len(p_tags):
                    next_p = p_tags[j]
                    next_content = next_p.get_text(strip=True)

                    # 如果遇到下一个问题，停止
                    if next_content.startswith('问题'):
                        break

                    # 否则，将这个<p>标签的内容添加到答案中
                    if next_content and next_content != '--':  # 跳过空行和分隔符
                        answer_parts.append(next_content)

                    j += 1

                # 合并所有答案段落
                answer_text = '\n\n'.join(answer_parts).strip()

                if question_text and answer_text:
                    qa_pairs.append({
                        'question': question_text,
                        'answer': answer_text
                    })

                # 跳过已处理的<p>标签
                i = j - 1

            i += 1
    else:
        # 方法2：使用<strong>标签和文本内容解析（适用于<br />换行的页面）
        # 获取所有文本内容，包括<br>标签
        content_text = content_div.get_text(separator='\n', strip=True)

        # 按行分割
        lines = content_text.split('\n')

        i = 0
        while i < len(lines):
            line = lines[i].strip()

            # 检查是否是问题行
            if line.startswith('问题'):
                question_text = line

                # 开始收集答案内容
                answer_parts = []

                # 继续遍历后续行，直到遇到下一个问题
                j = i + 1
                while j < len(lines):
                    next_line = lines[j].strip()

                    # 如果遇到下一个问题，停止
                    if next_line.startswith('问题'):
                        break

                    # 否则，将这行内容添加到答案中
                    if next_line and next_line != '--':
                        answer_parts.append(next_line)

                    j += 1

                # 合并所有答案段落
                answer_text = '\n\n'.join(answer_parts).strip()

                if question_text and answer_text:
                    qa_pairs.append({
                        'question': question_text,
                        'answer': answer_text
                    })

                # 跳过已处理的行
                i = j - 1

            i += 1

    return qa_pairs, publish_date

def load_existing_data():
    """加载已存在的数据"""
    try:
        data_file = os.path.join(_DATA_DIR, 'fada_wang_data.json')
        if os.path.exists(data_file):
            with open(data_file, 'r', encoding='utf-8') as f:
                return json.load(f)
    except Exception as e:
        print(f"加载现有数据失败: {e}")
    return []

def save_data(data):
    """保存数据"""
    os.makedirs(_DATA_DIR, exist_ok=True)
    data_file = os.path.join(_DATA_DIR, 'fada_wang_data.json')
    with open(data_file, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"数据已保存到: {data_file}")

def crawl_all_links(incremental=False):
    """爬取所有链接

    Args:
        incremental: 是否增量更新，True则只爬取新增的批次
    """
    # 加载现有数据
    existing_data = load_existing_data()
    existing_titles = {item['title'] for item in existing_data} if existing_data else set()

    all_data = []

    if incremental and existing_data:
        print("使用增量更新模式，只爬取新增的批次...")
        all_data = existing_data.copy()

    for title, url in links:
        # 如果是增量更新且该批次已存在，跳过
        if incremental and title in existing_titles:
            print(f"跳过已存在的批次: {title}")
            continue

        print(f"正在爬取: {title}")

        # 检查是否是缺失批次
        if url is None:
            # 使用补充数据
            if title in MISSING_BATCHES_DATA:
                supplement = MISSING_BATCHES_DATA[title]
                all_data.append({
                    'title': title,
                    'url': supplement['url'],
                    'qa_pairs': supplement['qa_pairs'],
                    'publish_date': supplement['publish_date'],
                    'crawl_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                    'source': 'supplement'  # 标记为补充数据
                })
                print(f"  使用补充数据，提取到 {len(supplement['qa_pairs'])} 个问答")
            else:
                print(f"  警告: 找不到补充数据")
            continue

        html = fetch_page(url)

        if html:
            qa_pairs, publish_date = parse_content(html)

            if qa_pairs:  # 只有成功提取到问答才添加
                all_data.append({
                    'title': title,
                    'url': url,
                    'qa_pairs': qa_pairs,
                    'publish_date': publish_date,
                    'crawl_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                    'source': 'court.gov.cn'  # 标记来源
                })
                print(f"  提取到 {len(qa_pairs)} 个问答，发布时间: {publish_date}")
            else:
                print(f"  警告: 未能提取到问答内容")
        else:
            print(f"  获取失败")

    return all_data

def generate_searchable_html(data):
    """生成可全文检索的HTML页面"""

    # 构建JavaScript数据
    js_data = []
    for item in data:
        for idx, qa in enumerate(item['qa_pairs']):
            # 去除问题前缀"问题X："或"问题："（保留问题序号）
            question = qa['question']
            # 答案前缀"答疑意见："或"答疑："不去除，保留原始格式
            answer = qa['answer']

            js_data.append({
                'batch': item['title'],
                'url': item['url'],
                'date': item.get('publish_date', '未知日期'),
                'question': question,
                'answer': answer
            })

    # 获取当前日期
    current_date = datetime.now().strftime('%Y年%m月%d日')

    html_template = f'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>法答网精选答问 - 全文检索</title>
    <style>
        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}

        body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", sans-serif;
            background: linear-gradient(135deg, #8B0000 0%, #B22222 100%);
            min-height: 100vh;
            padding: 20px;
        }}

        .container {{
            max-width: 1200px;
            margin: 0 auto;
        }}

        .header-search-container {{
            background: white;
            padding: 25px 30px;
            border-radius: 20px;
            box-shadow: 0 10px 40px rgba(0,0,0,0.1);
            margin-bottom: 20px;
            position: relative;
            z-index: 100;
            transition: all 0.4s cubic-bezier(0.4, 0, 0.2, 1);
        }}

        .header-search-container.sticky {{
            position: fixed;
            top: 0;
            left: 50%;
            transform: translateX(-50%);
            max-width: 1200px;
            width: 90%;
            padding: 15px 20px;
            border-radius: 0 0 15px 15px;
            margin: 0;
            box-shadow: 0 5px 30px rgba(0,0,0,0.2);
            animation: slideDown 0.4s cubic-bezier(0.4, 0, 0.2, 1);
        }}

        @keyframes slideDown {{
            from {{
                opacity: 0;
                transform: translateX(-50%) translateY(-20px);
            }}
            to {{
                opacity: 1;
                transform: translateX(-50%) translateY(0);
            }}
        }}

        .header-search-container.sticky .header-title,
        .header-search-container.sticky .header-subtitle,
        .header-search-container.sticky .header-stats {{
            opacity: 0;
            height: 0;
            margin: 0;
            padding: 0;
            overflow: hidden;
            transition: opacity 0.3s ease, height 0.3s ease, margin 0.3s ease, padding 0.3s ease;
        }}

        .header-search-container.sticky .search-row {{
            margin: 0;
            gap: 10px;
        }}

        .header-search-container.sticky .search-box {{
            padding: 10px 15px;
            margin: 0;
            box-shadow: none;
            background: transparent;
        }}

        .header-search-container.sticky .search-input {{
            padding: 8px 12px;
            font-size: 13px;
        }}

        .header-search-container.sticky .search-stats {{
            display: none;
        }}

        .header-search-container.sticky .fuzzy-search-toggle {{
            padding: 0 10px;
        }}

        .header-search-container.sticky .toggle-switch {{
            width: 40px;
            height: 20px;
        }}

        .header-search-container.sticky .toggle-slider:before {{
            height: 14px;
            width: 14px;
            left: 3px;
            bottom: 3px;
        }}

        .header-search-container.sticky .toggle-switch input:checked + .toggle-slider:before {{
            transform: translateX(20px);
        }}

        .header-search-container.sticky .toggle-label {{
            font-size: 12px;
        }}

        .header-content {{
            text-align: center;
        }}

        .header-title {{
            color: #333;
            margin-bottom: 8px;
            font-size: 28px;
        }}

        .header-subtitle {{
            color: #666;
            font-size: 13px;
            margin-bottom: 12px;
        }}

        .header-stats {{
            color: #666;
            font-size: 14px;
        }}

        .search-row {{
            margin-top: 20px;
            display: flex;
            align-items: center;
            gap: 15px;
        }}

        .search-box {{
            flex: 1;
            background: rgba(139, 0, 0, 0.05);
            padding: 20px 25px;
            border-radius: 15px;
            border: 1px solid rgba(139, 0, 0, 0.1);
            display: flex;
            flex-direction: column;
        }}

        .search-input {{
            width: 100%;
            padding: 14px 20px;
            font-size: 15px;
            border: 2px solid #e0e0e0;
            border-radius: 10px;
            outline: none;
            transition: all 0.3s;
        }}

        .search-input:focus {{
            border-color: #8B0000;
            box-shadow: 0 0 0 3px rgba(139, 0, 0, 0.1);
        }}

        .search-stats {{
            margin-top: 12px;
            color: #666;
            font-size: 13px;
        }}

        .stats {{
            color: #8B0000;
            font-weight: bold;
        }}

        .fuzzy-search-toggle {{
            margin-top: 0;
            display: flex;
            align-items: center;
            justify-content: center;
            gap: 10px;
            flex-shrink: 0;
            padding: 0 15px;
        }}

        .toggle-switch {{
            position: relative;
            width: 50px;
            height: 26px;
        }}

        .toggle-switch input {{
            opacity: 0;
            width: 0;
            height: 0;
        }}

        .toggle-slider {{
            position: absolute;
            cursor: pointer;
            top: 0;
            left: 0;
            right: 0;
            bottom: 0;
            background-color: #ccc;
            transition: 0.4s;
            border-radius: 34px;
        }}

        .toggle-slider:before {{
            position: absolute;
            content: "";
            height: 18px;
            width: 18px;
            left: 4px;
            bottom: 4px;
            background-color: white;
            transition: 0.4s;
            border-radius: 50%;
        }}

        .toggle-switch input:checked + .toggle-slider {{
            background-color: #8B0000;
        }}

        .toggle-switch input:checked + .toggle-slider:before {{
            transform: translateX(24px);
        }}

        .toggle-label {{
            font-size: 14px;
            color: #666;
        }}

        .results {{
            display: grid;
            gap: 20px;
        }}

        .qa-card {{
            background: white;
            padding: 30px;
            border-radius: 15px;
            box-shadow: 0 5px 20px rgba(0,0,0,0.1);
            transition: transform 0.3s, box-shadow 0.3s;
        }}

        .qa-card:hover {{
            transform: translateY(-5px);
            box-shadow: 0 10px 30px rgba(0,0,0,0.15);
        }}

        .qa-batch {{
            display: inline-block;
            background: linear-gradient(135deg, #8B0000 0%, #B22222 100%);
            color: white;
            padding: 5px 15px;
            border-radius: 20px;
            font-size: 13px;
            margin-bottom: 10px;
        }}

        .qa-batch-date {{
            color: #999;
            font-size: 12px;
            margin-bottom: 15px;
            font-style: italic;
        }}

        .qa-question {{
            color: #333;
            font-size: 18px;
            font-weight: 600;
            margin-bottom: 15px;
            line-height: 1.6;
        }}

        .qa-question-link {{
            text-decoration: none;
            display: block;
            transition: all 0.3s;
        }}

        .qa-question-link:hover {{
            transform: translateX(5px);
        }}

        .qa-question-link:hover .qa-question {{
            color: #8B0000;
        }}

        .qa-answer {{
            color: #666;
            font-size: 15px;
            line-height: 1.8;
            white-space: pre-wrap;
            text-indent: 2em;
        }}

        .qa-answer .highlight {{
            background: #fff3cd;
            padding: 2px 4px;
            border-radius: 3px;
        }}

        .no-results {{
            text-align: center;
            padding: 60px 20px;
            background: white;
            border-radius: 15px;
            color: #999;
            font-size: 18px;
        }}

        .footer {{
            text-align: center;
            padding: 30px;
            color: rgba(255,255,255,0.8);
            font-size: 14px;
            margin-top: 40px;
        }}

        .container-with-sidebar {{
            display: flex;
            gap: 20px;
            position: relative;
        }}

        .main-content {{
            flex: 1;
        }}

        .sidebar {{
            width: 280px;
            flex-shrink: 0;
            position: sticky;
            top: 20px;
            max-height: calc(100vh - 40px);
            overflow-y: auto;
            background: white;
            border-radius: 15px;
            box-shadow: 0 5px 20px rgba(0,0,0,0.1);
            padding: 20px;
            display: flex;
            flex-direction: column;
        }}

        .sidebar-title {{
            font-size: 18px;
            font-weight: 600;
            color: #333;
            margin-bottom: 15px;
            padding-bottom: 10px;
            border-bottom: 2px solid #8B0000;
        }}

        .batch-list {{
            list-style: none;
            overflow-y: auto;
            flex: 1;
        }}

        .batch-item {{
            padding: 10px 15px;
            margin-bottom: 8px;
            border-radius: 8px;
            cursor: pointer;
            transition: all 0.3s;
            font-size: 13px;
            color: #666;
            border-left: 3px solid transparent;
        }}

        .batch-item:hover {{
            background: linear-gradient(135deg, rgba(139, 0, 0, 0.05) 0%, rgba(178, 34, 34, 0.05) 100%);
            border-left-color: #8B0000;
            transform: translateX(5px);
        }}

        .batch-item.active {{
            background: linear-gradient(135deg, #8B0000 0%, #B22222 100%);
            color: white;
            border-left-color: white;
        }}

        .sidebar-search {{
            margin-bottom: 15px;
            padding-bottom: 15px;
            border-bottom: 1px solid #e0e0e0;
        }}

        .sidebar-search input {{
            width: 100%;
            padding: 10px 15px;
            font-size: 14px;
            border: 1px solid #e0e0e0;
            border-radius: 8px;
            outline: none;
            transition: all 0.3s;
        }}

        .sidebar-search input:focus {{
            border-color: #8B0000;
            box-shadow: 0 0 0 3px rgba(139, 0, 0, 0.1);
        }}

        .batch-count {{
            display: inline-block;
            background: rgba(0,0,0,0.1);
            padding: 2px 8px;
            border-radius: 10px;
            font-size: 11px;
            margin-left: 8px;
        }}

        .sidebar .batch-item.active .batch-count {{
            background: rgba(255,255,255,0.3);
        }}

        @media (max-width: 1024px) {{
            .container-with-sidebar {{
                flex-direction: column;
            }}

            .sidebar {{
                width: 100%;
                position: relative;
                top: 0;
                max-height: none;
                order: -1;
            }}

            .header-search-container.sticky {{
                width: 95%;
                padding: 12px 15px;
            }}
        }}

        @media (max-width: 768px) {{
            body {{
                padding: 10px;
            }}

            .header-search-container {{
                padding: 20px;
            }}

            .header-title {{
                font-size: 24px;
            }}

            .header-subtitle {{
                font-size: 12px;
            }}

            .header-stats {{
                font-size: 12px;
            }}

            .search-box {{
                padding: 15px;
            }}

            .search-input {{
                padding: 12px 15px;
                font-size: 14px;
            }}

            .header-search-container.sticky {{
                width: 100%;
                left: 0;
                transform: none;
                padding: 10px 15px;
            }}

            .header-search-container.sticky .search-input {{
                padding: 8px 12px;
                font-size: 13px;
            }}

            .fuzzy-search-toggle {{
                flex-wrap: wrap;
            }}

            .toggle-switch {{
                width: 44px;
                height: 22px;
            }}

            .toggle-label {{
                font-size: 13px;
            }}
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header-search-container" id="headerSearchContainer">
            <div class="header-content">
                <h1 class="header-title">法答网精选答问</h1>
                <p class="header-subtitle">最高人民法院权威解答 · 全文检索系统</p>
                <p class="header-stats">示丁某律师末次更新于{current_date}</p>
            </div>

            <div class="search-row">
                <div class="search-box">
                    <input
                        type="text"
                        class="search-input"
                        id="searchInput"
                        placeholder="输入关键词搜索，如：合同、赔偿、破产..."
                        autocomplete="off"
                    >
                    <div class="search-stats">
                        共收录 <span class="stats" id="totalStats">{len(js_data)}</span> 条问答，
                        找到 <span class="stats" id="matchStats">{len(js_data)}</span> 条匹配
                    </div>
                </div>
                <div class="fuzzy-search-toggle">
                    <label class="toggle-switch">
                        <input type="checkbox" id="fuzzyToggle" checked>
                        <span class="toggle-slider"></span>
                    </label>
                    <span class="toggle-label">全局模糊搜索</span>
                </div>
            </div>
        </div>

        <div class="container-with-sidebar">
            <div class="main-content">
                <div class="results" id="results"></div>
            </div>

            <div class="sidebar">
                <div class="sidebar-title">批次导航</div>
                <div class="sidebar-search">
                    <input
                        type="text"
                        id="sidebarSearch"
                        placeholder="搜索批次..."
                    >
                </div>
                <ul class="batch-list" id="batchList"></ul>
            </div>
        </div>

        <div class="footer">
            数据来源：最高人民法院官网 | 最后更新：{current_date}
        </div>
    </div>

    <script>
        const qaData = {json.dumps(js_data, ensure_ascii=False)};
        let currentSearchTerm = '';
        let fuzzySearchEnabled = true;

        function highlightText(text, searchTerm) {{
            if (!searchTerm) return text;

            const regex = new RegExp(`(${{searchTerm.replace(/[.*+?^${{}}()|[\\]\\\\]/g, '\\\\$&')}})`, 'gi');
            return text.replace(regex, '<span class="highlight">$1</span>');
        }}

        function fuzzyMatch(text, searchTerm) {{
            if (!searchTerm) return true;

            // 将搜索词拆分成字符
            const chars = searchTerm.toLowerCase().split('');
            let textIndex = 0;
            let charIndex = 0;
            const lowerText = text.toLowerCase();

            // 检查所有字符是否按顺序出现
            while (textIndex < lowerText.length && charIndex < chars.length) {{
                if (lowerText[textIndex] === chars[charIndex]) {{
                    charIndex++;
                }}
                textIndex++;
            }}

            return charIndex === chars.length;
        }}

        function renderResults(data, searchTerm = '') {{
            const resultsDiv = document.getElementById('results');
            const matchStats = document.getElementById('matchStats');

            matchStats.textContent = data.length;

            if (data.length === 0) {{
                resultsDiv.innerHTML = '<div class="no-results">没有找到匹配的问答，请尝试其他关键词</div>';
                return;
            }}

            resultsDiv.innerHTML = data.map((item, index) => `
                <div class="qa-card">
                    <span class="qa-batch">${{item.batch}}</span>
                    <div class="qa-batch-date">发布时间：${{item.date}}</div>
                    <a href="${{item.url}}" target="_blank" class="qa-question-link">
                        <div class="qa-question">
                            ${{highlightText(item.question, searchTerm)}}
                        </div>
                    </a>
                    <div class="qa-answer">
                        ${{highlightText(item.answer, searchTerm)}}
                    </div>
                </div>
            `).join('');
        }}

        function search(query) {{
            currentSearchTerm = query.trim();

            if (!currentSearchTerm) {{
                renderResults(qaData);
                return;
            }}

            const results = qaData.filter(item => {{
                const question = item.question.toLowerCase();
                const answer = item.answer.toLowerCase();
                const batch = item.batch.toLowerCase();
                const search = currentSearchTerm.toLowerCase();

                if (fuzzySearchEnabled) {{
                    // 模糊搜索：检查字符是否按顺序出现
                    return fuzzyMatch(question, search) ||
                           fuzzyMatch(answer, search) ||
                           fuzzyMatch(batch, search);
                }} else {{
                    // 精确搜索：检查是否包含完整字符串
                    return question.includes(search) ||
                           answer.includes(search) ||
                           batch.includes(search);
                }}
            }});

            renderResults(results, currentSearchTerm);
        }}

        // 渲染批次导航
        function renderSidebar(data) {{
            const batchList = document.getElementById('batchList');
            const batches = {{}};

            // 按批次分组统计
            data.forEach(item => {{
                const batch = item.batch;
                if (!batches[batch]) {{
                    batches[batch] = {{
                        count: 0,
                        items: []
                    }};
                }}
                batches[batch].count++;
                batches[batch].items.push(item);
            }});

            // 生成批次列表
            const sortedBatches = Object.keys(batches).reverse();
            batchList.innerHTML = sortedBatches.map(batch => `
                <li class="batch-item" data-batch="${{batch.replace(/"/g, '&quot;')}}">
                    ${{batch}}
                    <span class="batch-count">${{batches[batch].count}}</span>
                </li>
            `).join('');

            // 添加点击事件
            document.querySelectorAll('.batch-item').forEach(item => {{
                item.addEventListener('click', () => {{
                    const batch = item.getAttribute('data-batch');
                    filterByBatch(batch);

                    // 高亮当前批次
                    document.querySelectorAll('.batch-item').forEach(el => el.classList.remove('active'));
                    item.classList.add('active');
                }});
            }});
        }}

        // 按批次筛选
        function filterByBatch(batchName) {{
            const filteredData = qaData.filter(item => item.batch === batchName);
            renderResults(filteredData);
        }}

        // 显示所有批次
        function showAllBatches() {{
            renderResults(qaData);
            document.querySelectorAll('.batch-item').forEach(el => el.classList.remove('active'));
        }}

        // 搜索批次
        function searchBatches(query) {{
            const items = document.querySelectorAll('.batch-item');
            const lowerQuery = query.toLowerCase();

            items.forEach(item => {{
                const batchName = item.textContent.toLowerCase();
                if (batchName.includes(lowerQuery)) {{
                    item.style.display = 'block';
                }} else {{
                    item.style.display = 'none';
                }}
            }});
        }}

        // 初始化
        document.getElementById('searchInput').addEventListener('input', (e) => {{
            search(e.target.value);
        }});

        document.getElementById('fuzzyToggle').addEventListener('change', (e) => {{
            fuzzySearchEnabled = e.target.checked;
            search(document.getElementById('searchInput').value);
        }});

        document.getElementById('sidebarSearch').addEventListener('input', (e) => {{
            searchBatches(e.target.value);
        }});

        // 滚动悬浮效果
        const headerSearchContainer = document.getElementById('headerSearchContainer');
        let lastScrollTop = 0;

        window.addEventListener('scroll', () => {{
            const scrollTop = window.pageYOffset || document.documentElement.scrollTop;

            if (scrollTop > 100) {{
                headerSearchContainer.classList.add('sticky');
            }} else {{
                headerSearchContainer.classList.remove('sticky');
            }}

            lastScrollTop = scrollTop;
        }});

        // 初始渲染
        renderSidebar(qaData);
        renderResults(qaData);
    </script>
</body>
</html>'''

    return html_template

def main():
    """主函数"""
    print("开始爬取法答网精选答问...")
    print("=" * 60)

    # 爬取所有链接（增量模式）
    all_data = crawl_all_links(incremental=True)

    print("=" * 60)
    print(f"共爬取 {len(all_data)} 批精选答问")

    # 保存原始数据
    save_data(all_data)

    # 生成可检索的HTML（输出到脚本所在目录）
    html = generate_searchable_html(all_data)
    html_path = os.path.join(_SCRIPT_DIR, 'fada_wang_search.html')
    with open(html_path, 'w', encoding='utf-8') as f:
        f.write(html)

    print(f"检索页面已生成: {html_path}")
    print("完成！")

if __name__ == '__main__':
    main()
