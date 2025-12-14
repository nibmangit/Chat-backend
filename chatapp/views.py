from django.shortcuts import render
from rest_framework import generics, permissions, status
from rest_framework.response import Response
from django.contrib.auth.models import User
from django.shortcuts import get_object_or_404
from .models import *
from .serializers import *
from rest_framework.exceptions import PermissionDenied

class CreateUserView(generics.CreateAPIView):
    queryset = User.objects.all()
    serializer_class = UserSerializer 

class UserListView(generics.ListAPIView):
    queryset = User.objects.all()
    serializer_class = UserListSerializer
    permission_classes = [permissions.IsAuthenticated]

class ConversationListView(generics.ListAPIView):
    serializer_class = ConversationSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return Conversation.objects.filter(participants=self.request.user).prefetch_related('participants')
    
    def create(self, request, *args, **kwargs):
        participant_data = request.data.get('participants', [])
        if len(participant_data) != 2:
            return Response({"error": "A conversation must have exactly two participants."}, status=status.HTTP_400_BAD_REQUEST)
        
        if str(request.user.id) not in map(str, participant_data):
            raise PermissionDenied("You must be a participant in the conversation.")
        users =User.objects.filter(id__in=participant_data)
        if users.count() != 2:
            return Response({"error": "A conversation must have exactly two valid participants."}, status=status.HTTP_400_BAD_REQUEST)
        
        existing_conversation = Conversation.objects.filter(
            participants__id=participant_data[0]).filter(
                participants__id=participant_data[1]).distinct()
        if existing_conversation.exists():
            return Response ({"error": "A conversation already exist between these participants"}, status=status.HTTP_400_BAD_REQUEST)
        conversation = Conversation.objects.create()
        conversation.participants.set(users)
        serializer = self.get_serializer(conversation)
        return Response(serializer.data, status=status.HTTP_201_CREATED)
    
class MessageListCreateView(generics.ListCreateAPIView): 
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        conversation_id = self.kwargs['conversation_id']
        conversation = self.get_conversation(conversation_id)
        return conversation.messages.order_by('timestamp')
        
    
    def get_serializer(self, *args, **kwargs):
        if self.request.method == 'POST':
            return CreateMessageSerializer
        return MessageSerializer(*args, **kwargs)
    
    def perform_create(self, serializer):
        conversation_id = self.kwargs['conversation_id']
        conversation = self.get_conversation(conversation_id)
        serializer.save(sender=self.request.user, conversation=conversation)

    def get_conversation(self, conversation_id):
        conversation = get_object_or_404(Conversation, id=conversation_id)
        if self.request.user not in conversation.participants.all():
            raise PermissionDenied("You are not a participant in this conversation.")
        return conversation

class MessageRetriveDestroyView(generics.RetrieveDestroyAPIView):
    permission_classes =[permissions.IsAuthenticated]
    serializer_class = [MessageSerializer]

    def get_queryset(self):
        conversation_id = self.kwargs['conversation_id']
        return Message.objects.filter(conversation__id=conversation_id)
    
    def perform_destroy(self, instance):
        if instance.sender != self.request.user:
            raise PermissionDenied("You can only delete your own messages.")
        instance.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)