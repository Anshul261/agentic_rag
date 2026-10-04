import unittest
import bucket_gpu_bench as b

class FakeApi:
    def __init__(self,outputs):self.outputs=iter(outputs);self.prompts=[]
    def call(self,*args,**kwargs):
        self.prompts.append(args[1])
        return {'value':{'ranked':next(self.outputs)},'sec':2,'usage':{'prompt_tokens':100,'completion_tokens':10,'estimated_cost':.001},'model':'Qwen/Qwen3.8-27B'}

class RankingTests(unittest.TestCase):
    def setUp(self):
        b.PAGES=[{'doc':'A','page':0},{'doc':'A','page':1},{'doc':'B','page':0}]
        self.q={'question':'What was revenue?'};self.snippets={'0':'Revenue 10','1':'Revenue 20','2':'Revenue 30'}
    def test_numeric_string_ids_preserve_order(self):
        r=b.qwen_rank(FakeApi([['2','0']]),self.q,[0,1,2],self.snippets)
        self.assertEqual(r['ranked'],[2,0]);self.assertEqual(r['schema_repairs'],0)
    def test_invalid_document_names_are_retried_not_mapped_to_arbitrary_pages(self):
        r=b.qwen_rank(FakeApi([['A'],[1,0]]),self.q,[0,1,2],self.snippets)
        self.assertEqual(r['ranked'],[1,0]);self.assertEqual(r['schema_repairs'],1)
        self.assertEqual(r['sec'],4);self.assertEqual(r['usage']['prompt_tokens'],200)
        self.assertAlmostEqual(r['usage']['estimated_cost'],.002)
    def test_boolean_and_out_of_bounds_ids_are_rejected(self):
        with self.assertRaises(ValueError):b.qwen_rank(FakeApi([[True],[3],[-1],[]]),self.q,[0,1,2],self.snippets)
    def test_retrieval_does_not_see_reference_or_evidence(self):
        api=FakeApi([[1,0]]);q={**self.q,'answer':'SECRET_REFERENCE','evidence':[{'evidence_text':'SECRET_EVIDENCE'}]}
        b.qwen_rank(api,q,[0,1,2],self.snippets)
        self.assertNotIn('SECRET_REFERENCE',api.prompts[0]);self.assertNotIn('SECRET_EVIDENCE',api.prompts[0])

class ReferenceJudgeTests(unittest.TestCase):
    def test_correctness_prompt_excludes_retrieved_context(self):
        class CaptureApi:
            def call(self,model,prompt,tokens):self.prompt=prompt;return {'value':{'correct':False}}
        api=CaptureApi();q={'question':'What was revenue?','answer':'$10 million','evidence':[{'evidence_text':'CONTEXT_SENTINEL'}]}
        b.reference_judge(api,q,'Insufficient evidence')
        self.assertIn('$10 million',api.prompt);self.assertIn('Insufficient evidence',api.prompt)
        self.assertNotIn('CONTEXT_SENTINEL',api.prompt)

if __name__=='__main__':unittest.main()
