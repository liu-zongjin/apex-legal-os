import asyncio
import unittest
from unittest.mock import patch
from backend.public_case_web import build_wikisource_queries,_cache_key
from backend.public_case_semantics import review_context

class RecallTests(unittest.TestCase):
    def test_relation_anchor_is_added_to_every_alternative_without_topic_rules(self):
        for anchor in ['劳动关系','出资义务','商标侵权','行政协议']:
            plan={'context_terms':[anchor],'research_paths':[{'id':'p0','queries':['行为甲 结果乙']},{'id':'p1','queries':['行为丙 结果乙']}]}
            routes=build_wikisource_queries(plan)
            self.assertEqual(len(routes),2)
            self.assertTrue(all(anchor in r['query'] for r in routes))
    def test_generic_remedy_does_not_replace_specific_relationship_anchor(self):
        plan={'context_terms':['特定交易关系','解除'],'research_paths':[{'id':'p0','queries':['解除 行为甲']} ]}
        self.assertIn('特定交易关系',build_wikisource_queries(plan)[0]['query'])
    def test_fact_excerpt_uses_synonyms_to_find_late_evidence(self):
        from backend.public_case_semantics import evidence_cases
        case={'title':'匿名裁判','source_kind':'public_web','adjudicated_facts':'日期2020年其他事项。'*1000+'法院查明甲方已经实际履约。','holding':'法院认为。'}
        facts=evidence_cases([case],[{'required_facts':['履行完毕']}],[['履行','履约']])[0]['facts']
        self.assertIn('已经实际履约',facts)
    def test_changed_relation_does_not_reuse_candidate_cache(self):
        self.assertNotEqual(_cache_key({'context_terms':['甲关系']},5),_cache_key({'context_terms':['乙关系']},5))
    def test_counter_review_sees_neighbouring_limit_and_actual_rationale(self):
        case={'holding_original':'法院认为，到场办理手续，尚未完成接收。因其他条件不成立而驳回。'}
        assessment={'quote':'因其他条件不成立而驳回。','fact_checks':[{'quote':'到场办理手续'}]}
        context=review_context(case,assessment)
        self.assertTrue(any('尚未完成接收' in p for p in context))
        self.assertTrue(any('其他条件' in p for p in context))

class StreamingReadsTests(unittest.IsolatedAsyncioTestCase):
    async def test_a_slow_search_does_not_delay_a_fast_query_body(self):
        import httpx
        from backend.public_case_discovery import discover_cases
        slow_done=False;body_before_slow=[]
        class Routes:
            def __init__(self,*args):pass
            async def public_get(self,url):
                nonlocal slow_done
                if 'google.com' in url:
                    if 'slow' in url:await asyncio.sleep(.15);slow_done=True
                    text='<a href="https://example.org/fast"><h3>匿名判决</h3></a>'
                elif 'bing.com' in url:text='<rss><channel></channel></rss>'
                elif 'sogou.com' in url:text='<html></html>'
                else:body_before_slow.append(not slow_done);text='<article>法院原文</article>'
                return httpx.Response(200,text=text,headers={'content-type':'text/html'},request=httpx.Request('GET',url))
            async def aclose(self):pass
        plan={'research_paths':[{'id':'p0','queries':['fast']},{'id':'p1','queries':['slow']}],'queries':[]}
        with patch('backend.public_case_transport.CaseRoutes',Routes),patch('backend.public_case_discovery.parse_page',return_value={'title':'匿名判决'}):
            result=await discover_cases(plan)
        self.assertTrue(any(body_before_slow));self.assertEqual(len(result['cases']),1)
