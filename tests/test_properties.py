import pytest

from self_contained_draft.properties import PropertyInlineError, inline_property_macros


def test_inline_property_macros_replaces_configured_lookup_and_removes_assignments():
    text = (
        r"\ExplSyntaxOn"
        "\n"
        r"\prop_if_exist:NF \g_equilibrium_steady_prop { \prop_new:N \g_equilibrium_steady_prop }"
        "\n"
        r"\prop_gput:Nnn \g_equilibrium_steady_prop {baseline_pti} {0.282}"
        "\n"
        r"\cs_if_exist:NF \steady { \cs_new:Npn \steady #1 { \prop_item:Nn \g_equilibrium_steady_prop {#1} } }"
        "\n"
        r"\ExplSyntaxOff"
        "\n"
        r"PTI is \steady{baseline_pti}."
    )

    result = inline_property_macros(text, ("steady",))

    assert result.text == (
        r"\ExplSyntaxOn"
        "\n"
        r"\cs_if_exist:NF \steady { \cs_new:Npn \steady #1 { \prop_item:Nn \g_equilibrium_steady_prop {#1} } }"
        "\n"
        r"\ExplSyntaxOff"
        "\n"
        "PTI is 0.282."
    )
    assert result.macros == ("steady",)
    assert result.replacements == 1
    assert result.removed_assignments == 1


def test_inline_property_macros_replaces_lookup_inside_latex_expression():
    text = (
        r"\cs_new:Npn \steady #1 { \prop_item:Nn \g_equilibrium_steady_prop {#1} }"
        "\n"
        r"\prop_gput:Nnn \g_equilibrium_steady_prop {share} {0.375}"
        "\n"
        r"\topct{\fpeval{1.0 - \steady{share}}}"
    )

    result = inline_property_macros(text, ("steady",))

    assert result.text == (
        r"\cs_new:Npn \steady #1 { \prop_item:Nn \g_equilibrium_steady_prop {#1} }"
        "\n"
        r"\topct{\fpeval{1.0 - 0.375}}"
    )


def test_inline_property_macros_preserves_spaces_after_values_ending_in_control_words():
    text = (
        r"\cs_new:Npn \param #1 { \prop_item:Nn \g_equilibrium_param_prop {#1} }"
        "\n"
        r"\prop_gput:Nnn \g_equilibrium_param_prop {shock} {0.1980\unskip}"
        "\n"
        r"\param{shock} so"
    )

    result = inline_property_macros(text, ("param",))

    assert "0.1980\\unskip{} so" in result.text


def test_inline_property_macros_only_touches_configured_macros():
    text = (
        r"\cs_new:Npn \steady #1 { \prop_item:Nn \g_equilibrium_steady_prop {#1} }"
        "\n"
        r"\cs_new:Npn \param #1 { \prop_item:Nn \g_equilibrium_param_prop {#1} }"
        "\n"
        r"\prop_gput:Nnn \g_equilibrium_steady_prop {share} {0.375}"
        "\n"
        r"\prop_gput:Nnn \g_equilibrium_param_prop {beta} {0.96}"
        "\n"
        r"\steady{share} and \param{beta}"
    )

    result = inline_property_macros(text, ("steady",))

    assert r"\prop_gput:Nnn \g_equilibrium_param_prop {beta} {0.96}" in result.text
    assert r"\param{beta}" in result.text
    assert "0.375 and" in result.text
    assert result.removed_assignments == 1


def test_inline_property_macros_raises_for_missing_key():
    text = (
        r"\cs_new:Npn \steady #1 { \prop_item:Nn \g_equilibrium_steady_prop {#1} }"
        "\n"
        r"\prop_gput:Nnn \g_equilibrium_steady_prop {known} {1}"
        "\n"
        r"\steady{missing}"
    )

    with pytest.raises(PropertyInlineError, match=r"\\steady\{missing\}"):
        inline_property_macros(text, ("steady",))


def test_inline_property_macros_raises_for_missing_lookup_definition():
    with pytest.raises(PropertyInlineError, match=r"\\steady"):
        inline_property_macros(r"\steady{share}", ("steady",))
