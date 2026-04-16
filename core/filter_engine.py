"""
过滤引擎
支持将条件列表转换为 pandas 布尔掩码
"""

from typing import List, Tuple, Union, Any
import pandas as pd


class FilterEngine:
    """条件过滤执行器"""

    @staticmethod
    def apply_conditions(
        df: pd.DataFrame,
        conditions: List[Tuple[str, str, Any]]
    ) -> pd.DataFrame:
        """
        根据条件列表筛选 DataFrame

        Parameters
        ----------
        df : pd.DataFrame
            待筛选的数据
        conditions : List[Tuple[str, str, Any]]
            条件列表，每个元素为 (列名, 操作符, 值)
            支持的操作符: '>', '<', '>=', '<=', '==', '!=', 'between'

        Returns
        -------
        pd.DataFrame
            满足所有条件的行组成的 DataFrame
        """
        if not conditions:
            return df.copy()

        mask = pd.Series(True, index=df.index)

        for col, op, val in conditions:
            if col not in df.columns:
                raise KeyError(f"列 '{col}' 不存在于 DataFrame 中")

            if op == ">":
                mask &= (df[col] > val)
            elif op == "<":
                mask &= (df[col] < val)
            elif op == ">=":
                mask &= (df[col] >= val)
            elif op == "<=":
                mask &= (df[col] <= val)
            elif op == "==":
                mask &= (df[col] == val)
            elif op == "!=":
                mask &= (df[col] != val)
            elif op == "between":
                if not isinstance(val, (tuple, list)) or len(val) != 2:
                    raise ValueError("'between' 操作符的值必须为包含两个元素的元组或列表")
                mask &= df[col].between(val[0], val[1])
            else:
                raise ValueError(f"不支持的操作符: {op}")

        return df[mask].copy()