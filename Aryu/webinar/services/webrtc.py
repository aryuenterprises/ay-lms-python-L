# webinar/services/webrtc.py

def webrtc_offer_payload(offer_sdp, sender_id):
    return {
        "type": "webrtc_offer",
        "payload": {
            "sdp": offer_sdp,
            "from": sender_id,
        }
    }


def webrtc_answer_payload(answer_sdp, sender_id):
    return {
        "type": "webrtc_answer",
        "payload": {
            "sdp": answer_sdp,
            "from": sender_id,
        }
    }


def webrtc_ice_payload(candidate):
    """
    candidate should be dict:
    {
        candidate,
        sdpMid,
        sdpMLineIndex
    }
    """
    return {
        "type": "ice_candidate",
        "payload": candidate,
    }
