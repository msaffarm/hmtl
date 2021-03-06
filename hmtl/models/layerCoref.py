# coding: utf-8

import os
import sys
import logging
from typing import Dict
from overrides import overrides

import torch

from allennlp.common import Params
from allennlp.common.checks import ConfigurationError
from allennlp.data import Vocabulary
from allennlp.models.model import Model
from allennlp.modules import Seq2SeqEncoder, TextFieldEmbedder
from allennlp.nn import RegularizerApplicator, InitializerApplicator
from allennlp.modules.text_field_embedders import BasicTextFieldEmbedder
from allennlp.modules import FeedForward
from allennlp.models.crf_tagger import CrfTagger

from hmtl.modules.text_field_embedders import ShortcutConnectTextFieldEmbedder
from hmtl.models.relation_extraction import RelationExtractor
from hmtl.models import CoreferenceCustom

logger = logging.getLogger(__name__)  # pylint: disable=invalid-name


@Model.register("coref_custom")
class LayerCoref(Model):
    """
    A class that implement the one task of HMTL model: Coref (Lee et al).
    
    Parameters
    ----------
    vocab: ``allennlp.data.Vocabulary``, required.
        The vocabulary fitted on the data.
    params: ``allennlp.common.Params``, required
        Configuration parameters for the multi-task model.
    regularizer: ``allennlp.nn.RegularizerApplicator``, optional (default = None)
        A reguralizer to apply to the model's layers.
    """

    def __init__(self, vocab: Vocabulary, params: Params, regularizer: RegularizerApplicator = None):

        super(LayerCoref, self).__init__(vocab=vocab, regularizer=regularizer)

        # Base text Field Embedder
        text_field_embedder_params = params.pop("text_field_embedder")
        text_field_embedder = BasicTextFieldEmbedder.from_params(vocab=vocab, params=text_field_embedder_params)
        self._text_field_embedder = text_field_embedder

        ##############
        # Coref Stuffs
        ##############
        coref_params = params.pop("coref")

        # Encoder
        encoder_coref_params = coref_params.pop("encoder")
        encoder_coref = Seq2SeqEncoder.from_params(encoder_coref_params)
        self._encoder_coref = encoder_coref

        # Tagger: Coreference
        tagger_coref_params = coref_params.pop("tagger")
        eval_on_gold_mentions = tagger_coref_params.pop_bool("eval_on_gold_mentions", False)
        init_params = tagger_coref_params.pop("initializer", None)
        initializer = (
            InitializerApplicator.from_params(init_params) if init_params is not None else InitializerApplicator()
        )

        tagger_coref = CoreferenceCustom(
            vocab=vocab,
            text_field_embedder=self._text_field_embedder,
            context_layer=self._encoder_coref,
            mention_feedforward=FeedForward.from_params(tagger_coref_params.pop("mention_feedforward")),
            antecedent_feedforward=FeedForward.from_params(tagger_coref_params.pop("antecedent_feedforward")),
            feature_size=tagger_coref_params.pop_int("feature_size"),
            max_span_width=tagger_coref_params.pop_int("max_span_width"),
            spans_per_word=tagger_coref_params.pop_float("spans_per_word"),
            max_antecedents=tagger_coref_params.pop_int("max_antecedents"),
            lexical_dropout=tagger_coref_params.pop_float("lexical_dropout", 0.2),
            initializer=initializer,
            regularizer=regularizer,
            eval_on_gold_mentions=eval_on_gold_mentions,
        )
        self._tagger_coref = tagger_coref
        if eval_on_gold_mentions:
            self._tagger_coref._eval_on_gold_mentions = True

        logger.info("Multi-Task Learning Model has been instantiated.")

    @overrides
    def forward(self, tensor_batch, for_training: bool = False, task_name: str = "coref") -> Dict[str, torch.Tensor]:
        # pylint: disable=arguments-differ

        tagger = getattr(self, "_tagger_%s" % task_name)

        if task_name == "coref" and tagger._eval_on_gold_mentions:
            if for_training:
                tagger._use_gold_mentions = False
            else:
                tagger._use_gold_mentions = True

        return tagger.forward(**tensor_batch)

    @overrides
    def get_metrics(self, task_name: str, reset: bool = False, full: bool = False) -> Dict[str, float]:

        task_tagger = getattr(self, "_tagger_" + task_name)
        if full and task_name == "coref":
            return task_tagger.get_metrics(reset=reset, full=full)
        else:
            return task_tagger.get_metrics(reset)

    @classmethod
    def from_params(cls, vocab: Vocabulary, params: Params, regularizer: RegularizerApplicator) -> "LayerCoref":
        return cls(vocab=vocab, params=params, regularizer=regularizer)
