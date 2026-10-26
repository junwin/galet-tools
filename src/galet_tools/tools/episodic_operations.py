"""Small tools matching galet-memory's explicit episodic operations.

These delegate to the common adapter, so MCP and application hosts share the
same account checks, serialization and backend calls.
"""
from copy import deepcopy

from galet_tools.framework.handler_v2 import HandlerV2
from galet_tools.tools.episodic_memory_handler import EpisodicMemoryHandler

# Required and optional arguments for each backend operation. The account is
# supplied by the trusted execution host, not an editable client form field.
_OPERATIONS = {
    'list_sessions': ((), ('count', 'cursor')),
    'get_session': (('session_id',), ()),
    'create_session': ((), ('session_id', 'friendly_name', 'context_name', 'tags', 'metadata')),
    'update_session': (('session_id', 'changes'), ()),
    'delete_session': (('session_id',), ()),
    'delete_sessions': (('session_ids',), ()),
    'clear_session_events': (('session_id',), ('expected_last_event_id',)),
    'append_event': (('session_id', 'event'), ('expected_last_event_id',)),
    'append_events': (('session_id', 'events'), ('expected_last_event_id',)),
    'get_event': (('session_id', 'event_id'), ()),
    'get_recent_events': (('session_id',), ('count', 'event_kinds', 'actors', 'before_event_id')),
    'get_events_by_period': (('session_id', 'start', 'end'), ('count', 'event_kinds', 'actors', 'cursor')),
    'get_exchange': (('session_id', 'correlation_id'), ()),
    'invalidate_exchange': (('session_id', 'correlation_id'), ('expected_last_event_id',)),
    'get_digest': (('session_id', 'digest_id'), ()),
    'list_digests': (('session_id',), ('count', 'cursor')),
    'search_digests': (('query',), ('session_id', 'count')),
}


class EpisodicOperationHandler(HandlerV2):
    ACTION = ''
    NAME = ''

    def __init__(self, memory=None):
        self.memory = memory

    @classmethod
    def name(cls):
        return cls.NAME

    @classmethod
    def tool_def(cls):
        required, optional = _OPERATIONS[cls.ACTION]
        source = EpisodicMemoryHandler.tool_def()['parameters']['properties']
        properties = {key: deepcopy(source[key]) for key in (*required, *optional)}
        if 'count' in properties:
            default = {'get_recent_events': 10, 'get_events_by_period': 100, 'search_digests': 3}.get(cls.ACTION, 20)
            properties['count'].update(default=default, description='Maximum records to return. Zero explicitly returns none.')
        return {
            'type': 'function', 'name': cls.NAME,
            'description': f'{cls.ACTION.replace("_", " ").capitalize()} for the trusted execution account. '
                           'Uses the configured episodic store and galet-memory pagination/ownership rules.',
            'parameters': {'type': 'object', 'properties': properties,
                           'required': list(required), 'additionalProperties': False},
            'strict': False,
        }

    @classmethod
    def result_schema(cls):
        return EpisodicMemoryHandler.result_schema()

    def execute(self, args, *, account_name='auto', **context):
        allowed = self.tool_def()['parameters']['properties']
        if set(args) - set(allowed):
            return {'ok': False, 'tool': self.NAME, 'action': self.ACTION,
                    'error': 'Unsupported fields for this episodic operation'}
        result = EpisodicMemoryHandler(self.memory).execute(
            {'action': self.ACTION, **args}, account_name=account_name, **context)
        result['tool'] = self.NAME
        return result


EPISODIC_OPERATION_HANDLERS = tuple(
    type('Episodic' + ''.join(part.capitalize() for part in action.split('_')) + 'Handler',
         (EpisodicOperationHandler,), {'NAME': 'episodic_' + action, 'ACTION': action,
                                     '__module__': __name__})
    for action in _OPERATIONS
)
EPISODIC_OPERATION_NAMES = frozenset(cls.NAME for cls in EPISODIC_OPERATION_HANDLERS)
