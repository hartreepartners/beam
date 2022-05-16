import logging
from apache_beam.runners.runner import PipelineRunner
from apache_beam.runners.direct.bundle_factory import BundleFactory
from apache_beam.runners.direct.clock import RealClock
from apache_beam.options.pipeline_options import DirectOptions
#from apache_beam.options.pipeline_options import StandardOptions
from apache_beam.options.value_provider import RuntimeValueProvider
from apache_beam.runners.runner import PipelineResult
from apache_beam.runners.runner import PipelineState

__all__ = ['PythonRunner']

_LOGGER = logging.getLogger(__name__)


class PythonPipelineResult(PipelineResult):
  """A DirectPipelineResult provides access to info about a pipeline."""
  def __init__(self, executor, evaluation_context):
    super().__init__(PipelineState.RUNNING)
    self._executor = executor
    self._evaluation_context = evaluation_context

  def __del__(self):
    if self._state == PipelineState.RUNNING:
      _LOGGER.warning(
          'The DirectPipelineResult is being garbage-collected while the '
          'DirectRunner is still running the corresponding pipeline. This may '
          'lead to incomplete execution of the pipeline if the main thread '
          'exits before pipeline completion. Consider using '
          'result.wait_until_finish() to wait for completion of pipeline '
          'execution.')

  def wait_until_finish(self, duration=None):
    if not PipelineState.is_terminal(self.state):
      if duration:
        raise NotImplementedError(
            'DirectRunner does not support duration argument.')
      try:
        self._executor.await_completion()
        self._state = PipelineState.DONE
      except:  # pylint: disable=broad-except
        self._state = PipelineState.FAILED
        raise
    return self._state

  def aggregated_values(self, aggregator_or_name):
    return self._evaluation_context.get_aggregator_values(aggregator_or_name)

  def metrics(self):
    return self._evaluation_context.metrics()

  def cancel(self):
    """Shuts down pipeline workers.

    For testing use only. Does not properly wait for pipeline workers to shut
    down.
    """
    self._state = PipelineState.CANCELLING
    self._executor.shutdown()
    self._state = PipelineState.CANCELLED

class PythonRunner(PipelineRunner):
  """Executes a single pipeline on the local machine."""
  @staticmethod
  def is_fnapi_compatible():
    return False

  def run_pipeline(self, pipeline, options):
    # TODO: Move imports to top. Pipeline <-> Runner dependency cause problems
    # with resolving imports when they are at top.
    # pylint: disable=wrong-import-position
    #from apache_beam.pipeline import PipelineVisitor
    from apache_beam.runners.direct.consumer_tracking_pipeline_visitor import \
      ConsumerTrackingPipelineVisitor
    from apache_beam.runners.direct.evaluation_context import EvaluationContext
    from apache_beam.runners.direct.executor import Executor
    from apache_beam.runners.direct.transform_evaluator import \
      TransformEvaluatorRegistry

    clock = RealClock()

    # Performing configured PTransform overrides.
    #pipeline.replace_all(_get_transform_overrides(options))

    _LOGGER.info('Running pipeline with DirectRunner.')
    self.consumer_tracking_visitor = ConsumerTrackingPipelineVisitor()
    pipeline.visit(self.consumer_tracking_visitor)

    evaluation_context = EvaluationContext(
        options,
        BundleFactory(
            stacked=options.view_as(
                DirectOptions).direct_runner_use_stacked_bundle),
        self.consumer_tracking_visitor.root_transforms,
        self.consumer_tracking_visitor.value_to_consumers,
        self.consumer_tracking_visitor.step_names,
        self.consumer_tracking_visitor.views,
        clock)

    executor = Executor(
        self.consumer_tracking_visitor.value_to_consumers,
        TransformEvaluatorRegistry(evaluation_context),
        evaluation_context)
    # DirectRunner does not support injecting
    # PipelineOptions values at runtime
    RuntimeValueProvider.set_runtime_options({})
    # Start the executor. This is a non-blocking call, it will start the
    # execution in background threads and return.
    executor.start(self.consumer_tracking_visitor.root_transforms)
    result = PythonPipelineResult(executor, evaluation_context)

    return result

