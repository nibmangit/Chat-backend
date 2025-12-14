from asgiref.sync import sync_to_async
from channels.db import database_sync_to_async
import json
import jwt
from channels.generic.websocket import AsyncWebsocketConsumer

from django.conf import settings 
from urllib.parse import parse_qs 

class ChatConsumer(AsyncWebsocketConsumer):
    async def connect(self): 
        query_string = self.scope['query_string'].decode('utf-8')
        params = parse_qs(query_string)
        token = params.get('token', [None])[0] # Extract token from query params
        if token:
            try:
                decode_data = jwt.decode(token, settings.SECRET_KEY, algorithms=["HS256"])
                self.user = await self.get_user(decode_data['user_id']) # Fetch user asynchronously
                self.scope['user'] = self.user

            except jwt.ExpiredSignatureError:
                await self.close(code=4001)  # Token expired
                return
        else:
            await self.close(code=4000)  # Close The connection if No token provided
            return
        self.conversation_id = self.scope['url_route']['kwargs']['conversation_id']
        self.room_group_name = f'chat_{self.conversation_id}'
        # Add channel to conversation group
        await self.channel_layer.group_add(
            self.room_group_name,
            self.channel_name
        )

        # Accept the WebSocket connection
        await self.accept()

        user_data = await self.get_user_data(self.user)
        await self.channel_layer.group_send(
            self.room_group_name,{
                'type':'online_status',
                'online_user':[user_data],
                'status':'online',
            }
        )

    async def disconnect(self, close_code):
        # notify others about the disconnect
        user_data = await self.get_user_data(self.scope['user'])
        await self.channel_layer.group_send(
            self.room_group_name,{
                'type':'online_status',
                'online_user':[user_data],
                'status':'offline',
            }
        )
        # Remove channel from conversation group
        await self.channel_layer.group_discard(
            self.room_group_name,
            self.channel_name
        )

    async def receive(self, text_data):
        text_data_json = json.loads(text_data)
        event_type = text_data_json.get('type')

        if event_type == 'chat_message':
            message_content = text_data_json.get('message')
            user_id = text_data_json.get('user')

            try:
                user = await self.get_user(user_id)
                conversation = await self.get_conversation(self.conversation_id)
                from .serializers import UserListSerializer
                user_data = UserListSerializer(user).data

                #save message to database
                message = await self.save_message(conversation, user, message_content)
                # Broadcast message to conversation group
                await self.channel_layer.group_send(
                    self.room_group_name,{
                        'type':'chat_message',
                        'message':message.content,
                        'user':user_data,
                        'timestamp':message.timestamp.isoformat(),
                    }
                )
            except Exception as e:
                print(f"Error Saving message: {e}")
        elif event_type == "typing":
            try:
                user_data = await self.get_user_data(self.scope['user'])
                reciver_id = text_data_json.get('reciver_id')

                if reciver_id is not None:
                    if isinstance(reciver_id,(str, int, float)):
                        reciver_id = int(reciver_id)
                        
                        if reciver_id != self.scope['user'].id:
                            print(f"{user_data['username']} is typing...")
                            await self.channel_layer.group_send(
                                self.room_group_name,{
                                    'type':'typing',
                                    'user':user_data,
                                    'reciver_id':reciver_id,
                                }
                            )
                        else:
                            print(f"{user_id['username']} tried to send typing to himself.")
                    else:
                        print(f"Invalid reciver_id type: {type(reciver_id)}")
                else:
                    print("reciver_id is missing.")
            except Exception as e:
                print(f"Error parsing reciver ID: {e}") 
    
    #helper functions
    async def chat_message(self, event):
        message = event['message']
        user = event['user']
        timestamp = event['timestamp']
        await self.send(text_data=json.dumps({
            'type':'chat_message',
            'message':message,
            'user':user,
            'timestamp':timestamp,
        }))

    async def typing(self, event):
        user = event['user']
        reciver = event.get('reciver')
        is_typing = event.get('is_typing', False)
        await self.send(text_data=json.dumps({
            'type':'typing',
            'user':user,
            'reciver':reciver, 
            'is_typing':is_typing,
        }))

    async def online_status(self, event):
        await self.send(text_data=json.dumps(event))

    def get_user_model(self):
        from django.contrib.auth import get_user_model
        return get_user_model()
    
    @database_sync_to_async
    def get_user(self, user_id): 
        User = self.get_user_model() 
        return User.objects.get(id=user_id)
    
    @database_sync_to_async
    def get_user_data(self, user):
        from .serializers import UserListSerializer
        return UserListSerializer(user).data
    
    @sync_to_async
    def get_conversation(self, conversation_id):
        from .models import Conversation
        try:
            return Conversation.objects.get(id=conversation_id)
        except Conversation.DoesNotExist:
            print(f"Conversation with id {conversation_id} does not exist.")
            return None
        
    @sync_to_async
    def save_message(self, conversation, user, message_content):
        from .models import Message
        message = Message.objects.create(
            conversation=conversation,
            sender=user,
            content=message_content
        )
        return message