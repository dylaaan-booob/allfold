import pytest
from allfold.keywords import parse_keyword_expression, KeywordSyntaxError


def test_memory_ast_preserves_boolean_and_field_phrase_boundaries():
    from allfold.keywords import matches_fields
    ast = parse_keyword_expression('"graph learning" AND (statist* OR inference)')
    assert matches_fields(ast, ('Graph learning with statistical models',))
    assert not matches_fields(ast, ('A graph', 'learning statistical models'))
    assert not matches_fields(ast, ('Graph learning with algebra',))


@pytest.mark.parametrize('text', ['"graph learning"~2', 'learn?ng', '*learning', 'learn*ing', 'x AND NOT y'])
def test_retired_and_unsupported_syntax_is_rejected_before_requests(text):
    with pytest.raises(KeywordSyntaxError):
        parse_keyword_expression(text)
