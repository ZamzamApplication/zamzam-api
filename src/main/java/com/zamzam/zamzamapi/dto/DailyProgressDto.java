package com.zamzam.zamzamapi.dto;

import java.time.LocalDate;
import java.util.UUID;

public class DailyProgressDto {
  public UUID id;
  public UUID studentId;
  public UUID halaqaId;
  public LocalDate date;
  public String hifz;
  public String revision;
  public String remarks;
  public Integer rating;
  public long version;
}
