"""Order delivery evidence without letting arrival order regress confirmation."""
RANK={'Pending':0,'Failed':0,'Sent':1,'Delivered':2,'Read':3}

def advances(current, incoming, previous_time, incoming_time):
    old=RANK.get(current,0);new=RANK.get(incoming,0)
    # A delayed delivery/read confirmation is stronger than an earlier observed
    # state even when another provider timestamp was greater.
    if incoming_time<previous_time and not (new>=2 and new>old):
        return False
    if new<old and (incoming!='Failed' or old>=2):
        return False
    return current!=incoming or previous_time!=incoming_time
