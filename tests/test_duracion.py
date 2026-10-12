"""Una duración mínima explícita exige trabajo real, preservado entre iteraciones."""
from conftest import ScriptedLLM, tool_call
from skynet.scheduler import LongTaskRunner
from skynet.store import HECHA


async def test_explicit_minimum_prevents_early_finish(make_rt):
    llm = ScriptedLLM([
        ('', [tool_call('workspace__write_file', {'path':'mod.py', 'content':'VERSION = 1\ndef doble(x): return 2*x\n'})]),
        ('Primera versión.\nOBJETIVO_CUMPLIDO', None),
        ('', [tool_call('workspace__write_file', {'path':'QA.md', 'content':'Casos de igualdad y límites comprobados.'})]),
        ('Revisión completada.\nOBJETIVO_CUMPLIDO', None),
    ])
    rt=make_rt(llm)
    task=rt.store.create_task('x','Implementa doble y revisa casos límite.',agent='scheduler',repo='prueba',max_hours=1,
                              capabilities={'min_trabajo_seg':60})
    times=iter([0,0,0,30,30,30,61])
    out=await LongTaskRunner(rt,task.id,on_event=lambda *a:None,clock=lambda:next(times)).run()
    assert out.status==HECHA and out.iters_done==2
    assert out.capabilities['trabajo_seg']==61
    assert 'Duración mínima' in llm.calls[0]['messages'][1]['content']


async def test_partial_plan_is_valid_in_long_iteration(make_rt):
    llm=ScriptedLLM([
        ('', [tool_call('workspace__write_file',{'path':'.skynet/tarea-1/PLAN.md','content':'- [ ] Segunda fase\n'}),
              tool_call('workspace__write_file',{'path':'mod.py','content':'VERSION = 1\ndef doble(x): return 2*x\n'})]),
        ('Primera fase comprobada.',None),
    ])
    rt=make_rt(llm)
    task=rt.store.create_task('x','Dos fases.',agent='scheduler',repo='prueba',max_hours=1,max_iters=1)
    await LongTaskRunner(rt,task.id,on_event=lambda *a:None).run()
    assert len(llm.calls)==2 and rt.store.steps_for(task.id)[0].output_summary=='Primera fase comprobada.'
