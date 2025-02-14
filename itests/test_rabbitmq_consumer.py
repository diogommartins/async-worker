from asynctest import TestCase, skip
import asyncio

from asyncworker import App, RouteTypes


consume_callback_shoud_not_be_called = False
handler_with_requeue_called = 0
handler_without_requeue_called = 0
successful_message_value_is_equal = False


class RabbitMQConsumerTest(TestCase):
    async def setUp(self):
        self.queue_name = "test"
        self.app = App("127.0.0.1", "guest", "guest", 1)

    async def tearDown(self):
        await self.app[RouteTypes.AMQP_RABBITMQ]["connection"][
            "/"
        ].connection.channel.queue_delete(self.queue_name)
        handler_without_requeue_called = 0
        handler_with_requeue_called = 0

    async def test_process_one_successful_message(self):
        """
        Um worker com dois handlers um que publica e outro que lê a mensagem
        No final um ack() é chamado
        """
        message = {"key": "value"}

        @self.app.route([self.queue_name], type=RouteTypes.AMQP_RABBITMQ)
        async def handler(messages):
            global successful_message_value_is_equal
            successful_message_value_is_equal = (
                messages[0].body["key"] == message["key"]
            )

        await self.app.startup()
        queue = self.app[RouteTypes.AMQP_RABBITMQ]["connection"]["/"]
        await queue.connection._connect()
        await queue.connection.channel.queue_declare(self.queue_name)

        await queue.put(routing_key=self.queue_name, data=message)
        await asyncio.sleep(1)
        self.assertTrue(successful_message_value_is_equal)
        await self.app.shutdown()

    async def test_process_message_reject_with_requeue(self):
        """
        Causamos um erro no handler para que a mensagem seja rejeitada e
        recolocada na fila.
        O handler confirmará a mensagem na segunda tentativa (`msg.ack()`)
        """

        @self.app.route([self.queue_name], type=RouteTypes.AMQP_RABBITMQ)
        async def other_handler(messages):
            global handler_with_requeue_called
            if handler_with_requeue_called > 0:
                messages[0].accept()
            else:
                handler_with_requeue_called += 1
            value = messages[0].field  # AttributeError

        await self.app.startup()
        queue = self.app[RouteTypes.AMQP_RABBITMQ]["connection"]["/"]
        await queue.connection._connect()
        await queue.connection.channel.queue_declare(self.queue_name)

        await queue.put(
            routing_key=self.queue_name,
            data={"key": "handler_with_requeue_then_ack"},
        )
        await asyncio.sleep(2)
        self.assertEqual(1, handler_with_requeue_called)
        await self.app.shutdown()

    async def test_process_message_reject_without_requeue(self):
        """
        Adicionamos um handler que causa uma falha mas que joga a mensagem fora.
        Temos que conferir que o handler foi chamado
        """

        @self.app.route([self.queue_name], type=RouteTypes.AMQP_RABBITMQ)
        async def other_handler(messages):
            global handler_without_requeue_called
            handler_without_requeue_called += 1
            messages[0].reject(requeue=False)
            value = messages[0].field  # AttributeError

        await self.app.startup()
        queue = self.app[RouteTypes.AMQP_RABBITMQ]["connection"]["/"]
        await queue.connection._connect()
        await queue.connection.channel.queue_declare(self.queue_name)

        await queue.put(
            routing_key=self.queue_name, data={"key": "handler_without_requeue"}
        )
        await asyncio.sleep(2)
        self.assertEqual(1, handler_without_requeue_called)

        await self.app.shutdown()
        await queue.connection.close()

        async def callback(*args, **kwargs):
            global consume_callback_shoud_not_be_called
            consume_callback_shoud_not_be_called = True

        queue = self.app[RouteTypes.AMQP_RABBITMQ]["connection"]["/"]
        await queue.connection._connect()
        await queue.connection.channel.basic_consume(
            callback, queue_name=self.queue_name
        )
        await asyncio.sleep(5)
        self.assertFalse(consume_callback_shoud_not_be_called)
