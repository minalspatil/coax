# ------------------------------------------------------------------------------------------------ #
# MIT License                                                                                      #
#                                                                                                  #
# Copyright (c) 2020, Microsoft Corporation                                                        #
#                                                                                                  #
# Permission is hereby granted, free of charge, to any person obtaining a copy of this software    #
# and associated documentation files (the "Software"), to deal in the Software without             #
# restriction, including without limitation the rights to use, copy, modify, merge, publish,       #
# distribute, sublicense, and/or sell copies of the Software, and to permit persons to whom the    #
# Software is furnished to do so, subject to the following conditions:                             #
#                                                                                                  #
# The above copyright notice and this permission notice shall be included in all copies or         #
# substantial portions of the Software.                                                            #
#                                                                                                  #
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING    #
# BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND       #
# NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM,     #
# DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,   #
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.          #
# ------------------------------------------------------------------------------------------------ #

from inspect import signature
from collections import namedtuple

import jax
import jax.numpy as jnp
import numpy as onp
from gym.spaces import Space

from ..utils import safe_sample
from ..value_transforms import ValueTransform
from ..proba_dists import ProbaDist
from .base_func import BaseFunc, ExampleData, Inputs, ArgsType2


__all__ = (
    'V',
)


class V(BaseFunc):
    r"""

    A state value function :math:`v_\theta(s)`.

    Parameters
    ----------
    func : function

        A Haiku-style function that specifies the forward pass. The function signature must be the
        same as the example below.

    env : gym.Env

        The gym-style environment. This is used to validate the input/output structure of ``func``.

    observation_preprocessor : function, optional

        Turns a single observation into a batch of observations that are compatible with the
        corresponding probability distribution. If left unspecified, this defaults to:

        .. code:: python

            observation_preprocessor = ProbaDist(observation_space).preprocess_variate

        See also :attr:`coax.proba_dists.ProbaDist.preprocess_variate`.

    value_transform : ValueTransform or pair of funcs, optional

        If provided, the target for the underlying function approximator is transformed such that:

        .. math::

            \tilde{v}_\theta(S_t)\ \approx\ f(G_t)

        This means that calling the function involves undoing this transformation:

        .. math::

            v(s)\ =\ f^{-1}(\tilde{v}_\theta(s))

        Here, :math:`f` and :math:`f^{-1}` are given by ``value_transform.transform_func`` and
        ``value_transform.inverse_func``, respectively. Note that a ValueTransform is just a
        glorified pair of functions, i.e. passing ``value_transform=(func, inverse_func)`` works
        just as well.

    random_seed : int, optional

        Seed for pseudo-random number generators.

    """
    def __init__(
            self, func, env, observation_preprocessor=None, value_transform=None, random_seed=None):

        self.observation_preprocessor = observation_preprocessor
        self.value_transform = value_transform

        # defaults
        if self.observation_preprocessor is None:
            self.observation_preprocessor = ProbaDist(env.observation_space).preprocess_variate
        if self.value_transform is None:
            self.value_transform = ValueTransform(lambda x: x, lambda x: x)
        if not isinstance(self.value_transform, ValueTransform):
            self.value_transform = ValueTransform(*value_transform)

        super().__init__(
            func=func,
            observation_space=env.observation_space,
            action_space=None,
            random_seed=random_seed)

    def __call__(self, s):
        r"""

        Evaluate the value function on a state observation :math:`s`.

        Parameters
        ----------
        s : state observation

            A single state observation :math:`s`.

        Returns
        -------
        v : ndarray, shape: ()

            The estimated expected value associated with the input state observation ``s``.

        """
        S = self.observation_preprocessor(s)
        V, _ = self.function(self.params, self.function_state, self.rng, S, False)
        V = self.value_transform.inverse_func(V)
        return onp.asarray(V[0])

    @classmethod
    def example_data(cls, env, observation_preprocessor=None, batch_size=1, random_seed=None):

        if not isinstance(env.observation_space, Space):
            raise TypeError(
                "env.observation_space must be derived from gym.Space, "
                f"got: {type(env.observation_space)}")

        if observation_preprocessor is None:
            observation_preprocessor = ProbaDist(env.observation_space).preprocess_variate

        rnd = onp.random.RandomState(random_seed)

        # input: state observations
        S = [safe_sample(env.observation_space, rnd) for _ in range(batch_size)]
        S = [observation_preprocessor(s) for s in S]
        S = jax.tree_multimap(lambda *x: jnp.concatenate(x, axis=0), *S)

        return ExampleData(
            inputs=Inputs(args=ArgsType2(S=S, is_training=True), static_argnums=(1,)),
            output=jnp.asarray(rnd.randn(batch_size)),
        )

    def _check_signature(self, func):
        if tuple(signature(func).parameters) != ('S', 'is_training'):
            sig = ', '.join(signature(func).parameters)
            raise TypeError(
                f"func has bad signature; expected: func(S, is_training), got: func({sig})")

        # example inputs
        Env = namedtuple('Env', ('observation_space',))
        return self.example_data(
            env=Env(self.observation_space),
            observation_preprocessor=self.observation_preprocessor,
            batch_size=1,
            random_seed=self.random_seed,
        )

    def _check_output(self, actual, expected):
        if not isinstance(actual, jnp.ndarray):
            raise TypeError(
                f"func has bad return type; expected jnp.ndarray, got {actual.__class__.__name__}")

        if not jnp.issubdtype(actual.dtype, jnp.floating):
            raise TypeError(
                "func has bad return dtype; expected a subdtype of jnp.floating, "
                f"got dtype={actual.dtype}")

        if actual.shape != expected.shape:
            raise TypeError(
                f"func has bad return shape, expected: {expected.shape}, got: {actual.shape}")
