package com.challenge.evchargeops.exceptions;

public class MismatchedOldPasswordException extends RuntimeException {
    public MismatchedOldPasswordException(String message) {
        super(message);
    }
}
