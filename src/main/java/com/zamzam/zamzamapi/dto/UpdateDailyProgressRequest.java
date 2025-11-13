package com.zamzam.zamzamapi.dto;

public class UpdateDailyProgressRequest {
    private String hifz;
    private String revision;
    private String remarks;
    private Integer rating;

    public UpdateDailyProgressRequest() {}

    public UpdateDailyProgressRequest(String hifz, String revision, String remarks, Integer rating) {
        this.hifz = hifz;
        this.revision = revision;
        this.remarks = remarks;
        this.rating = rating;
    }

    public String getHifz() {
        return hifz;
    }

    public void setHifz(String hifz) {
        this.hifz = hifz;
    }

    public String getRevision() {
        return revision;
    }

    public void setRevision(String revision) {
        this.revision = revision;
    }

    public String getRemarks() {
        return remarks;
    }

    public void setRemarks(String remarks) {
        this.remarks = remarks;
    }

    public Integer getRating() {
        return rating;
    }

    public void setRating(Integer rating) {
        this.rating = rating;
    }
}