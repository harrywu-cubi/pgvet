from pgvet.plugins.base import Family, SchemaContext, Inferencer
from pgvet.core.findings import Finding, Severity
from pgvet.core.schemamodel import SchemaModel


class _Fires(Inferencer):
    id = "inferencer.test"
    name = "Test inferencer"
    def run(self, ctx):
        yield Finding(self.id, Severity.SUGGEST, "hi", "d")


def test_inferencer_family_and_applies_to():
    inf = _Fires()
    assert inf.family == Family.INFERENCER
    ctx = SchemaContext(schema=SchemaModel(), sampler=object())
    assert inf.applies_to(ctx) is True
    assert [f.plugin_id for f in inf.run(ctx)] == ["inferencer.test"]
