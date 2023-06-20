# ----------------------------------------------------------------------------
# Copyright (C) 2021-2023 Deepchecks (https://www.deepchecks.com)
#
# This file is part of Deepchecks.
# Deepchecks is distributed under the terms of the GNU Affero General
# Public License (version 3 or later).
# You should have received a copy of the GNU Affero General Public License
# along with Deepchecks.  If not, see <http://www.gnu.org/licenses/>.
# ----------------------------------------------------------------------------
#
"""module contains Data Duplicates check."""
from typing import List, Union

import numpy as np
from merge_args import merge_args
from typing_extensions import Literal

from deepchecks.core import CheckResult
from deepchecks.core.errors import DatasetValidationError
from deepchecks.core.fix_classes import FixResult, SingleDatasetCheckFixMixin
from deepchecks.tabular import Context, SingleDatasetCheck
from deepchecks.tabular._shared_docs import docstrings
from deepchecks.utils.abstracts.data_duplicates import DataDuplicatesAbstract
from deepchecks.utils.dataframes import select_from_dataframe
from deepchecks.utils.strings import format_list, format_percent
from deepchecks.utils.typing import Hashable

__all__ = ['DataDuplicates']


class DataDuplicates(SingleDatasetCheck, DataDuplicatesAbstract, SingleDatasetCheckFixMixin):
    """Checks for duplicate samples in the dataset.

    Parameters
    ----------
    columns : Union[Hashable, List[Hashable]] , default: None
        List of columns to check, if none given checks
        all columns Except ignored ones.
    ignore_columns : Union[Hashable, List[Hashable]] , default: None
        List of columns to ignore, if none given checks
        based on columns variable.
    n_to_show : int , default: 5
        number of most common duplicated samples to show.
    n_samples : int , default: 10_000_000
        number of samples to use for this check.
    random_state : int, default: 42
        random seed for all check internals.
    """

    def __init__(
            self,
            columns: Union[Hashable, List[Hashable], None] = None,
            ignore_columns: Union[Hashable, List[Hashable], None] = None,
            n_to_show: int = 5,
            n_samples: int = 10_000_000,
            random_state: int = 42,
            **kwargs
    ):
        super().__init__(**kwargs)
        self.columns = columns
        self.ignore_columns = ignore_columns
        self.n_to_show = n_to_show
        self.n_samples = n_samples
        self.random_state = random_state

    def run_logic(self, context: Context, dataset_kind):
        """Run check.

        Returns
        -------
        CheckResult
            percentage of duplicates and display of the top n_to_show most duplicated.
        """
        df = context.get_data_by_kind(dataset_kind).sample(self.n_samples, random_state=self.random_state).data
        df = select_from_dataframe(df, self.columns, self.ignore_columns)

        data_columns = list(df.columns)
        n_samples = df.shape[0]

        if n_samples == 0:
            raise DatasetValidationError('Dataset does not contain any data')

        # HACK: pandas have bug with groupby on category dtypes, so until it fixed, change dtypes manually
        category_columns = df.dtypes[df.dtypes == 'category'].index.tolist()
        if category_columns:
            df = df.astype({c: 'object' for c in category_columns})

        group_unique_data = df[data_columns].groupby(data_columns, dropna=False).size()
        n_unique = len(group_unique_data)

        percent_duplicate = 1 - (1.0 * int(n_unique)) / (1.0 * int(n_samples))

        if context.with_display and percent_duplicate > 0:
            # patched for anonymous_series
            # TODO: reset_index(name=...) can be used instead of this confusing hack
            is_anonymous_series = 0 in group_unique_data.keys().names
            if is_anonymous_series:
                new_name = str(group_unique_data.keys().names)
                new_index = group_unique_data.keys()
                new_index.names = [new_name if name == 0 else name for name in new_index.names]
                group_unique_data = group_unique_data.reindex(new_index)
            duplicates_counted = group_unique_data.reset_index().rename(columns={0: 'Number of Duplicates'})
            if is_anonymous_series:
                duplicates_counted.rename(columns={new_name: 0}, inplace=True)

            most_duplicates = duplicates_counted[duplicates_counted['Number of Duplicates'] > 1]. \
                nlargest(self.n_to_show, ['Number of Duplicates'])

            indexes = []
            for row in most_duplicates.iloc():
                indexes.append(format_list(df.index[np.all(df == row[data_columns], axis=1)].to_list()))

            most_duplicates['Instances'] = indexes

            most_duplicates = most_duplicates.set_index(['Instances', 'Number of Duplicates'])

            text = f'{format_percent(percent_duplicate)} of data samples are duplicates. '
            explanation = 'Each row in the table shows an example of duplicate data and the number of times it appears.'
            display = [text, explanation, most_duplicates]

        else:
            display = None

        return CheckResult(value=percent_duplicate, display=display)

    @docstrings
    @merge_args(SingleDatasetCheck.run)
    def fix(self, *args, keep: Literal['first', 'last', False] = 'first', **kwargs) \
            -> FixResult:
        """Run fix.

        Parameters
        ----------
        {additional_context_params:2*indent}
        keep : Literal['first', 'last', False], default: 'first'
            Whether to keep the first or last duplicate row.
            If False, all duplicates will be removed.

        Returns
        -------
        Dataset
            Dataset with fixed duplicates.
        """
        context = self.get_context(*args, **kwargs)
        dataset = context.train

        data = dataset.data.copy()
        data = select_from_dataframe(data, self.columns, self.ignore_columns)
        data.drop_duplicates(inplace=True, keep=keep)

        return FixResult(fixed_train=dataset.copy(data))
