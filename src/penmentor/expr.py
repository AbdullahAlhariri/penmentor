"""Claude's plot formulas, e.g. "x**2*exp(-x)", turned into numpy functions.

The text comes from a model that read your screen, so it is untrusted: only numbers, arithmetic, comparisons and the
names below get through; anything else (attributes, indexing, lambdas, imports, unknown names) is refused.
"""
import ast
import re

import numpy as np


def _factorial(x):
    from scipy.special import gamma
    return gamma(np.asarray(x, float) + 1)


FUNCS = {
    'sin': np.sin, 'cos': np.cos, 'tan': np.tan, 'sec': lambda x: 1 / np.cos(x), 'csc': lambda x: 1 / np.sin(x),
    'cot': lambda x: 1 / np.tan(x), 'arcsin': np.arcsin, 'arccos': np.arccos, 'arctan': np.arctan, 'asin': np.arcsin,
    'acos': np.arccos, 'atan': np.arctan, 'sinh': np.sinh, 'cosh': np.cosh, 'tanh': np.tanh, 'arcsinh': np.arcsinh,
    'arccosh': np.arccosh, 'arctanh': np.arctanh, 'exp': np.exp, 'log': np.log, 'ln': np.log, 'log10': np.log10,
    'log2': np.log2, 'sqrt': np.sqrt, 'cbrt': np.cbrt, 'abs': np.abs, 'sign': np.sign, 'floor': np.floor, 'ceil': np.ceil,
    'factorial': _factorial, 'where': np.where, 'min': np.minimum, 'max': np.maximum,
}
CONSTS = {'pi': np.pi, 'e': np.e, 'inf': np.inf, 'oo': np.inf}
ALIASES = {'theta': 't', 'θ': 't', 'π': 'pi', '∞': 'inf'}
NODES = (ast.Expression, ast.BinOp, ast.UnaryOp, ast.Call, ast.Name, ast.Load, ast.Constant, ast.Compare,
         ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Pow, ast.Mod, ast.USub, ast.UAdd, ast.Lt, ast.LtE, ast.Gt, ast.GtE)


def formula(src, names=('x',), finite=True):
    """f(**{name: array}) -> float array (NaN where undefined or infinite, unless finite=False).
    Raises ValueError for anything that is not a formula."""
    s = str(src).replace('^', '**').replace('−', '-').replace('·', '*')
    for a, b in ALIASES.items():
        s = re.sub(rf'(?<![\w]){a}(?![\w])', b, s)
    s = re.sub(r'(?<![\w.])(\d+\.?\d*)\s*(?![eE][-+]?\d)([a-zA-Z(])', r'\1*\2', s)  # 2x -> 2*x (not log10(x) or 1e-5)
    try:
        tree = ast.parse(s.strip(), mode='eval')
    except SyntaxError:
        raise ValueError(f'not a formula: {src!r}')
    for node in ast.walk(tree):
        if not isinstance(node, NODES):
            raise ValueError(f'not allowed in a formula: {type(node).__name__} in {src!r}')
        if isinstance(node, ast.Name) and node.id not in FUNCS and node.id not in CONSTS and node.id not in names:
            raise ValueError(f'unknown name {node.id!r} in {src!r}')
        if isinstance(node, ast.Call) and (not isinstance(node.func, ast.Name) or node.func.id not in FUNCS or node.keywords):
            raise ValueError(f'unknown function in {src!r}')
        if isinstance(node, ast.Constant):
            if type(node.value) not in (int, float):
                raise ValueError(f'not a number: {node.value!r} in {src!r}')
            node.value = float(node.value)  # float powers overflow to inf; int powers like 9**9**9 would hang
    code = compile(tree, '<formula>', 'eval')
    env = {'__builtins__': {}, **FUNCS, **CONSTS}

    def f(**kw):
        with np.errstate(all='ignore'):
            try:
                v = np.asarray(eval(code, env, {k: np.asarray(v, float) for k, v in kw.items()}), float)
            except OverflowError:
                v = np.asarray(np.inf)
        shape = np.broadcast(*map(np.asarray, kw.values())).shape if kw else ()
        v = np.broadcast_to(v, shape).astype(float)
        return np.where(np.isfinite(v), v, np.nan) if finite else v
    return f


def number(src, default=None):
    """A constant like "pi/2", "-inf" or 3 as a float."""
    if src in (None, ''):
        return default
    if isinstance(src, (int, float)):
        return float(src)
    v = float(formula(src, (), finite=False)())
    if np.isnan(v):
        raise ValueError(f'not a number: {src!r}')
    return v
