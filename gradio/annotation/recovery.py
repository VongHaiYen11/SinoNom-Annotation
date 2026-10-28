"""Process-lifetime checkpoints, independent of Gradio connection state."""
from copy import deepcopy
from uuid import uuid4


class RecoveryStore:
    version = 1

    def __init__(self):
        self.application = uuid4().hex
        self.contexts = {}

    def restore(self, tab, initial):
        if not isinstance(tab, str) or len(tab) > 128 or not tab:
            tab = uuid4().hex
        ctx = deepcopy(self.contexts.get(tab, initial))
        ctx.setdefault('_recovery', dict(tab=tab, generations={}))
        return ctx

    def rotate(self, ctx, path):
        if path and '_recovery' in ctx:
            ctx['_recovery'] = deepcopy(ctx['_recovery'])
            ctx['_recovery']['generations'][path] = uuid4().hex

    def metadata(self, ctx):
        recovery = ctx.get('_recovery')
        if not recovery:
            return None
        state = ctx['active']
        path = state.get('image_path')
        generation = recovery['generations'].setdefault(path or '', uuid4().hex)
        return dict(version=self.version, application=self.application,
                    tab=recovery['tab'], image=path, step=state['current_step'],
                    generation=generation, discardImage=ctx.get('_recovery_discard'))

    def checkpoint(self, ctx):
        metadata = self.metadata(ctx)
        if metadata:
            self.contexts[metadata['tab']] = deepcopy(ctx)
        return metadata
